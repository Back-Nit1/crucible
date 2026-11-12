import { ObservatoryClient } from "@/components/observatory/observatory-client";
import { buildObservatoryModel } from "@/components/observatory/observatory-model";
import { ErrorState } from "@/components/ui/data-state";
import { serverApi } from "@/lib/api/server";
import { publicEnv } from "@/lib/env";
import type { ObservatoryModel } from "@/components/observatory/observatory-model";

export const dynamic = "force-dynamic";

const CROWD_SIZE = 30;

async function liveModel(requested: string | undefined): Promise<ObservatoryModel> {
  const api = serverApi();
  const [choices, rounds] = await Promise.all([
    api.observatoryGenerations(),
    api.observatoryRounds().catch(() => []), // an older API without rounds still renders
  ]);
  const generationId =
    choices.find((choice) => choice.generation_id === requested)?.generation_id ??
    choices[0]?.generation_id;
  if (!generationId) throw new Error("No generation archive is available to replay.");
  const bundle = await api.observatoryBundle(generationId, CROWD_SIZE);
  return buildObservatoryModel(
    bundle.generation,
    { items: bundle.episodes, total: bundle.episodes.length, offset: 0, limit: 200 },
    { items: bundle.leaderboard, total: bundle.leaderboard.length, offset: 0, limit: 200 },
    bundle.focus,
    bundle.kill_rules,
    bundle.crowd,
    choices,
    rounds,
  );
}

// Sanitized sample fixtures have no crowd or picker: one recorded mission, as before.
async function sampleModel(): Promise<ObservatoryModel> {
  const api = serverApi();
  const generations = await api.generations();
  const generationId = generations.items[0]?.generation_id;
  if (!generationId) throw new Error("No generation archive is available to replay.");
  const [generation, episodes, leaderboard, killRules] = await Promise.all([
    api.generation(generationId),
    api.episodes({ generation_id: generationId, limit: 200 }),
    api.leaderboard(generationId),
    api.killRules(),
  ]);
  const showcase =
    episodes.items
      .filter((item) => item.termination === "success" && !item.killed)
      .sort((a, b) => b.tool_call_count - a.tool_call_count)[0] ?? episodes.items[0];
  if (!showcase) throw new Error("This generation has no recorded episodes.");
  const episode = await api.episode(showcase.episode_id);
  return buildObservatoryModel(generation, episodes, leaderboard, episode, killRules);
}

export default async function ObservatoryPage({
  searchParams,
}: {
  searchParams: Promise<{ generation?: string }>;
}) {
  const { generation } = await searchParams;
  const sample = publicEnv.NEXT_PUBLIC_DATA_MODE === "sample";
  let model: ObservatoryModel | null = null;
  let message = "The recorded world could not be mapped into the Observatory.";

  try {
    model = sample ? await sampleModel() : await liveModel(generation);
  } catch (error) {
    message = error instanceof Error ? error.message : message;
  }

  return model ? (
    <ObservatoryClient
      key={model.generationId}
      model={model}
      sample={sample}
      apiBaseUrl={publicEnv.NEXT_PUBLIC_API_BASE_URL}
    />
  ) : (
    <ErrorState title="Observatory unavailable" message={message} />
  );
}
