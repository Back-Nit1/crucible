import type {
  CrowdEpisode,
  Episode,
  GenerationChoice,
  LearningRound,
  EpisodeDetail,
  GenerationDetail,
  KillRule,
  LeaderboardRow,
  Page,
} from "@/lib/api/types";
import { asRecord, at, numberAt, stringAt } from "@/lib/records";

export type ObservatoryAgent = {
  id: string;
  variant: string;
  fitness: number | null;
  survivor: boolean;
  killCount: number;
  killRules: string[];
};

export type ObservatoryProduct = {
  id: string;
  category: string;
  mentions: number;
};

export type ObservatoryShop = {
  id: string;
  name: string;
  category: string;
  productIds: string[];
  visits: number;
};

export type ObservatoryRule = {
  id: string;
  label: string;
  description: string;
  fires: number;
};

export type ObservatoryStep = {
  sequence: number;
  tool: string;
  summary: string;
  references: string[];
  errorCode: string | null;
};

export type ObservatoryModel = {
  generationId: string;
  generationStatus: string;
  choices: GenerationChoice[];
  crowd: CrowdEpisode[];
  rounds: LearningRound[];
  seed: number | null;
  catalogHash: string | null;
  populationSize: number;
  survivors: number;
  culled: number;
  completedEpisodes: number | null;
  totalEpisodes: number;
  agents: ObservatoryAgent[];
  products: ObservatoryProduct[];
  shops: ObservatoryShop[];
  rules: ObservatoryRule[];
  mission: {
    request: string;
    budget: string | null;
    currency: string;
  };
  training: {
    currentCheckpoint: string;
    state: "scripted_replay" | "model_rollout";
  };
  episode: {
    id: string;
    agentId: string;
    task: string;
    category: string;
    fitness: number | null;
    killed: boolean;
    termination: string;
    finalAnswer: string;
    steps: ObservatoryStep[];
  };
  scripted: boolean;
};

function objectArray(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.map(asRecord) : [];
}

function numberRecord(value: unknown): Record<string, number> {
  const result: Record<string, number> = {};
  for (const [key, item] of Object.entries(asRecord(value))) {
    const parsed = typeof item === "number" ? item : Number(item);
    if (Number.isFinite(parsed)) result[key] = parsed;
  }
  return result;
}

export function buildObservatoryModel(
  generation: GenerationDetail,
  episodes: Page<Episode>,
  leaderboard: Page<LeaderboardRow>,
  episode: EpisodeDetail,
  killRules: KillRule[] = [],
  crowd: CrowdEpisode[] = [],
  choices: GenerationChoice[] = [],
  rounds: LearningRound[] = [],
): ObservatoryModel {
  const summary = generation.summary;
  const params = asRecord(at(summary, "params"));
  const episodeSummary = asRecord(at(summary, "episodes"));
  const fitnessByAgent = numberRecord(at(asRecord(at(summary, "fitness")), "by_genome"));
  const killsByAgent = asRecord(at(asRecord(at(summary, "kills")), "by_agent"));
  const leaderboardByAgent = new Map(leaderboard.items.map((row) => [row.agent_id, row]));
  const population = objectArray(at(summary, "population"));

  const agents = population.map((entry): ObservatoryAgent => {
    const id = stringAt(entry, "id") ?? "unknown-genome";
    const row = leaderboardByAgent.get(id);
    const ruleCounts = numberRecord(killsByAgent[id]);
    return {
      id,
      variant: stringAt(entry, "variant") ?? row?.variant ?? "unknown variant",
      fitness: fitnessByAgent[id] ?? row?.mean_fitness ?? null,
      survivor: row?.survivor ?? Object.keys(ruleCounts).length === 0,
      killCount: Object.values(ruleCounts).reduce((total, value) => total + value, 0),
      killRules: Object.keys(ruleCounts),
    };
  });

  // Older archives may not publish a population array. The leaderboard is still enough to render.
  if (!agents.length) {
    agents.push(
      ...leaderboard.items.map((row) => ({
        id: row.agent_id,
        variant: row.variant,
        fitness: row.mean_fitness,
        survivor: row.survivor,
        killCount: row.killed_episodes,
        killRules: row.kill_rules,
      })),
    );
  }

  const productMap = new Map<string, ObservatoryProduct>();
  for (const item of episodes.items) {
    for (const id of item.products_considered) {
      const current = productMap.get(id);
      productMap.set(id, {
        id,
        category: current?.category ?? item.category,
        mentions: (current?.mentions ?? 0) + 1,
      });
    }
  }
  // Crowd shoppers walk to the products their steps reference, so those need a place in the world too.
  for (const item of crowd) {
    for (const id of item.products) {
      if (!productMap.has(id)) productMap.set(id, { id, category: item.category, mentions: 1 });
    }
  }
  for (const id of episode.products_considered) {
    const current = productMap.get(id);
    productMap.set(id, {
      id,
      category: current?.category ?? episode.category,
      mentions: Math.max(1, current?.mentions ?? 0),
    });
  }

  const products = [...productMap.values()];
  const shops = [...new Set(products.map((product) => product.category))].map(
    (category): ObservatoryShop => {
      const inventory = products.filter((product) => product.category === category);
      return {
        id: `shop-${category.toLowerCase().replaceAll("_", "-")}`,
        name: category
          .split("_")
          .map((part) => part[0]?.toUpperCase() + part.slice(1).toLowerCase())
          .join(" "),
        category,
        productIds: inventory.map((product) => product.id),
        visits: inventory.reduce((total, product) => total + product.mentions, 0),
      };
    },
  );
  const parseStep = episode.replay.find((step) => step.tool === "parse_intent");
  const rawBudget = parseStep?.arguments.max_total;
  const budget =
    typeof rawBudget === "string" || typeof rawBudget === "number" ? String(rawBudget) : null;
  const rawRequest = parseStep?.arguments.raw_message;
  const currentCheckpoint = stringAt(episode.genome, "model_checkpoint") ?? "unknown-checkpoint";

  const ruleLabels: Record<string, string> = {
    K001_HALLUCINATED_PRODUCT: "Invented a product",
    K002_WRONG_REFUSAL: "Refused a valid purchase",
    K003_BUDGET_VIOLATION: "Exceeded the shopper's budget",
    K004_INSUFFICIENT_RESEARCH: "Skipped required research",
    K005_DUPLICATE_PAYMENT: "Attempted duplicate payment",
    K006_FABRICATED_REVIEW_EVIDENCE: "Invented review evidence",
    K007_SKIPPED_REVIEWS: "Skipped required reviews",
    K008_REVIEW_GAMING: "Gamed the review policy",
  };

  return {
    generationId: generation.generation_id,
    generationStatus: generation.status,
    choices,
    crowd,
    rounds,
    seed: generation.seed ?? null,
    catalogHash: generation.catalog_hash ?? null,
    populationSize: generation.population_size,
    survivors: generation.survivors,
    culled: Math.max(generation.population_size - generation.survivors, 0),
    completedEpisodes: numberAt(episodeSummary, "completed"),
    totalEpisodes: episodes.total,
    agents,
    products,
    shops,
    rules: killRules.map((rule) => ({
      id: rule.rule_id,
      label: ruleLabels[rule.rule_id] ?? rule.rule_id.replaceAll("_", " "),
      description: rule.description,
      fires: rule.kills,
    })),
    mission: {
      request: typeof rawRequest === "string" ? rawRequest : episode.task_text,
      budget,
      currency: "USD",
    },
    training: {
      currentCheckpoint,
      state: currentCheckpoint.startsWith("scripted") ? "scripted_replay" : "model_rollout",
    },
    episode: {
      id: episode.episode_id,
      agentId: episode.agent_id,
      task: episode.task_text,
      category: episode.category,
      fitness: episode.fitness,
      killed: episode.killed,
      termination: episode.termination,
      finalAnswer: episode.final_answer,
      steps: episode.replay.map((step) => ({
        sequence: step.sequence,
        tool: step.tool,
        summary: step.result_summary,
        references: step.result_references,
        errorCode: step.error_code,
      })),
    },
    scripted:
      stringAt(params, "model") === "scripted" ||
      stringAt(episode.genome, "model_checkpoint")?.startsWith("scripted") === true,
  };
}
