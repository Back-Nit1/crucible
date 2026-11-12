import { z } from "zod";

export const apiErrorSchema = z.object({
  error: z.object({ code: z.string(), message: z.string() }),
});

export const pageSchema = <T extends z.ZodType>(item: T) =>
  z.object({
    items: z.array(item),
    total: z.number().int().nonnegative(),
    offset: z.number().int().nonnegative(),
    limit: z.number().int().positive(),
  });

export const generationSchema = z.object({
  generation_id: z.string(),
  status: z.string(),
  population_size: z.number().int().nonnegative(),
  survivors: z.number().int().nonnegative(),
  kills: z.number().int().nonnegative(),
  seed: z.number().int().nullable().optional(),
  tasks: z.number().int().nonnegative().nullable().optional(),
  catalog_hash: z.string().nullable().optional(),
  runner: z.string().nullable().optional(),
  error: z.string().nullable().optional(),
});

export const generationDetailSchema = generationSchema.extend({
  summary: z.record(z.string(), z.unknown()),
});

export const episodeSchema = z.object({
  episode_id: z.string(),
  task_id: z.string(),
  agent_id: z.string(),
  generation_id: z.string(),
  split: z.string(),
  category: z.string(),
  fitness: z.number().nullable(),
  scored: z.boolean(),
  killed: z.boolean(),
  kill_rule_id: z.string().nullable(),
  kill_rule_version: z.number().int().nullable(),
  termination: z.string(),
  tool_call_count: z.number().int().nonnegative(),
  products_considered: z.array(z.string()),
  review_ids_cited: z.array(z.string()),
  final_answer: z.string(),
});

export const replayStepSchema = z.object({
  sequence: z.number().int().nonnegative(),
  tool: z.string(),
  arguments: z.record(z.string(), z.unknown()),
  result_references: z.array(z.string()),
  result_summary: z.string(),
  error_code: z.string().nullable(),
  timestamp: z.string(),
});

export const episodeDetailSchema = episodeSchema.extend({
  task_text: z.string(),
  catalog_hash: z.string().nullable(),
  seed: z.number().int().nullable(),
  replay: z.array(replayStepSchema),
  score_components: z.record(z.string(), z.unknown()),
  kills: z.array(
    z.object({
      rule_id: z.string(),
      rule_version: z.number().int(),
      description: z.string(),
      evidence: z.array(z.string()),
    }),
  ),
  payment_events: z.array(z.record(z.string(), z.unknown())),
  genome: z.record(z.string(), z.unknown()),
});

export const leaderboardSchema = z.object({
  rank: z.number().int().positive(),
  agent_id: z.string(),
  variant: z.string(),
  generation_id: z.string(),
  episodes: z.number().int().nonnegative(),
  mean_fitness: z.number(),
  killed_episodes: z.number().int().nonnegative(),
  kill_rules: z.array(z.string()),
  survivor: z.boolean(),
});

export const killLogSchema = z.object({
  episode_id: z.string(),
  agent_id: z.string(),
  generation_id: z.string(),
  task_id: z.string(),
  rule_id: z.string(),
  rule_version: z.number().int(),
  evidence: z.array(z.string()),
});

export const killRuleSchema = z.object({
  rule_id: z.string(),
  version: z.number().int(),
  description: z.string(),
  added_on: z.string(),
  enabled: z.boolean(),
  kills: z.number().int().nonnegative(),
});

export const documentSchema = z.object({
  id: z.string(),
  data: z.record(z.string(), z.unknown()),
});

export const ledgerRowSchema = z.object({
  mode: z.enum(["mock", "sandbox"]),
  episode_id: z.string(),
  event: z.string(),
  product_id: z.string().nullable(),
  amount: z.string().nullable(),
  references: z.array(z.string()),
});

export const healthSchema = z.object({ status: z.string() });
export const readySchema = z.object({
  status: z.string(),
  version: z.string(),
  checks: z.object({
    elastic_configured: z.boolean(),
    paypal_sandbox_configured: z.boolean(),
    model_configured: z.boolean(),
    demo_mode: z.boolean(),
  }),
});
export const loopStatusSchema = z.object({
  iterations: z.array(
    z.object({
      iteration_id: z.string(),
      next_stage: z.string().nullable(),
      stages: z.array(
        z.object({
          stage: z.string(),
          status: z.string(),
          evidence: z.string().optional(),
          detail: z.string().optional(),
          missing: z.array(z.string()).optional(),
        }),
      ),
    }),
  ),
  kill_switch: z.boolean(),
});
export const configSchema = z.object({
  version: z.string(),
  demo_mode: z.boolean(),
  payments: z.enum(["mock", "sandbox"]),
  require_all_in_quote: z.boolean(),
  catalog: z.string(),
  snapshot_as_of: z.string(),
  data_notice: z.string(),
});

export const reviewEvidenceSchema = z.object({
  claim: z.string(),
  review_ids: z.array(z.string()),
  excerpt: z.string().nullable().optional(),
  rating: z.number().nullable().optional(),
  date: z.string().nullable().optional(),
});
export const pickSchema = z.object({
  product_id: z.string(),
  title: z.string(),
  price: z.union([z.string(), z.number()]),
  currency: z.string(),
  source: z.string(),
  as_of: z.string(),
  snapshot: z.boolean(),
  reason: z.string(),
  review_evidence: z.array(reviewEvidenceSchema),
});
export const agentRunResultSchema = z.object({
  parsed_intent: z.record(z.string(), z.unknown()),
  steps: z.array(replayStepSchema),
  picks: z.array(pickSchema),
  no_match: z.boolean(),
  closest_product_id: z.string().nullable(),
  assumptions: z.array(z.string()),
  final_answer: z.string(),
  model: z.string(),
  latency_ms: z.number().int().nullable(),
  cost_usd: z.union([z.string(), z.number()]).nullable(),
});

export const proposeResultSchema = z.object({
  pending_order_id: z.string(),
  product_id: z.string(),
  total: z.union([z.string(), z.number()]),
  currency: z.string(),
  status: z.string(),
  approval_url: z.url().nullable(),
  quote_id: z.string().nullable(),
  quote_basis: z.string(),
});
export const confirmResultSchema = z.object({
  order_id: z.string(),
  capture_id: z.string(),
  amount: z.union([z.string(), z.number()]),
  currency: z.string(),
  status: z.string(),
});

const moneySchema = z.union([z.string(), z.number()]);
const eventBase = {
  seq: z.number().int().nonnegative(),
  at: z.string().nullable(),
};
const provenanceSchema = z.object({
  source: z.string(),
  as_of: z.string(),
  snapshot: z.boolean(),
  catalog_manifest_hash: z.string().nullable(),
  source_id: z.string().nullable(),
});

export const buyerEventSchema = z.discriminatedUnion("type", [
  z.object({
    ...eventBase,
    type: z.literal("intent_parsed"),
    category: z.string(),
    max_total: moneySchema,
    currency: z.string(),
    budget_source: z.enum(["buyer", "model_parse"]),
  }),
  z.object({
    ...eventBase,
    type: z.literal("assumptions"),
    assumptions: z.array(z.string()),
    unknown_constraints: z.array(z.string()),
  }),
  z.object({
    ...eventBase,
    type: z.literal("research"),
    tool: z.string(),
    summary: z.string(),
    references: z.array(z.string()),
  }),
  z.object({
    ...eventBase,
    type: z.literal("product_card"),
    product_id: z.string(),
    title: z.string(),
    brand: z.string().nullable(),
    category: z.string(),
    price: moneySchema,
    currency: z.string(),
    stock: z.object({
      status: z.enum(["unknown", "in_stock", "out_of_stock"]),
      units_by_variant: z.record(z.string(), z.number().int().nonnegative()),
    }),
    size_options: z.array(z.string()).nullable(),
    recommended: z.boolean(),
    provenance: provenanceSchema,
  }),
  z.object({
    ...eventBase,
    type: z.literal("review_citation"),
    product_id: z.string(),
    review_id: z.string(),
    source_review_id: z.string().nullable(),
    concern: z.string(),
    claim: z.string(),
    excerpt: z.string().nullable(),
    rating: z.number().nullable(),
    date: z.string().nullable(),
    provenance: provenanceSchema,
  }),
  z.object({
    ...eventBase,
    type: z.literal("comparison"),
    product_ids: z.array(z.string()),
    rows: z.record(z.string(), z.record(z.string(), z.string().nullable())),
  }),
  z.object({
    ...eventBase,
    type: z.literal("no_match"),
    reason: z.string(),
    why_it_misses: z.string(),
    closest_product_id: z.string().nullable(),
    closest_verified: z.boolean(),
    assumptions: z.array(z.string()),
  }),
  z.object({
    ...eventBase,
    type: z.literal("quote"),
    quote_id: z.string(),
    product_id: z.string(),
    variant: z.string(),
    currency: z.string(),
    subtotal: moneySchema,
    shipping: moneySchema.nullable(),
    tax: moneySchema.nullable(),
    discounts: moneySchema,
    total: moneySchema,
    basis: z.enum(["all_in", "item_price_only"]),
    unknown_components: z.array(z.string()),
    quoted_at: z.string(),
    expires_at: z.string(),
    fresh: z.boolean(),
    budget_cap: moneySchema,
    budget_checked_on: z.enum(["all_in_total", "item_price_total"]),
    within_budget: z.boolean(),
  }),
  z.object({
    ...eventBase,
    type: z.literal("confirmation_request"),
    pending_order_id: z.string(),
    quote_id: z.string(),
    total: moneySchema,
    currency: z.string(),
    basis: z.enum(["all_in", "item_price_only"]),
    summary: z.string(),
    requires_explicit_confirmation: z.boolean(),
  }),
  z.object({
    ...eventBase,
    type: z.literal("paypal_approval"),
    mode: z.enum(["sandbox", "mock"]),
    status: z.string(),
    approval_url: z.string().nullable(),
  }),
  z.object({
    ...eventBase,
    type: z.literal("receipt"),
    mode: z.enum(["sandbox", "mock"]),
    order_id: z.string(),
    capture_id: z.string(),
    amount: moneySchema,
    currency: z.string(),
    status: z.string(),
  }),
  z.object({
    ...eventBase,
    type: z.literal("error"),
    code: z.string(),
    message: z.string(),
    retryable: z.boolean(),
    action: z.enum(["retry", "requote", "rephrase", "set_budget", "reconfigure_model", "none"]),
  }),
]);

export const buyerRunSchema = z.object({
  run_id: z.string(),
  status: z.enum(["running", "awaiting_confirmation", "completed", "failed"]),
  events: z.array(buyerEventSchema),
  next_seq: z.number().int().nonnegative(),
  model: z.string().nullable(),
  tokens: z.number().int().nonnegative(),
  latency_ms: z.number().int().nonnegative(),
  cost_usd: moneySchema.nullable(),
  cost_known: z.boolean(),
});

export const crowdEpisodeSchema = z.object({
  episode_id: z.string(),
  agent_id: z.string(),
  task_id: z.string(),
  category: z.string(),
  checkpoint: z.string().nullable(),
  killed: z.boolean(),
  fitness: z.number().nullable(),
  termination: z.string(),
  products: z.array(z.string()),
  steps: z.array(
    z.object({
      tool: z.string(),
      references: z.array(z.string()),
      error_code: z.string().nullable(),
    }),
  ),
});

export const generationChoiceSchema = z.object({
  generation_id: z.string(),
  status: z.string(),
  published: z.boolean(),
  episodes: z.number().int().nonnegative(),
  population_size: z.number().int().nonnegative(),
  survivors: z.number().int().nonnegative(),
});

export const observatoryBundleSchema = z.object({
  generation: generationDetailSchema,
  episodes: z.array(episodeSchema),
  leaderboard: z.array(leaderboardSchema),
  kill_rules: z.array(killRuleSchema),
  focus: episodeDetailSchema,
  crowd: z.array(crowdEpisodeSchema),
});

export const trainingRunSchema = z.object({
  run_id: z.string(),
  algorithm: z.string().nullable(),
  base_model: z.string().nullable(),
  gpu: z.string().nullable(),
  status: z.string().nullable(),
  step: z.number().nullable(),
  total_steps: z.number().nullable(),
  resumed_from_step: z.number().nullable().optional(),
  loss: z.number().nullable(),
  losses: z.array(z.number()).nullable(),
  started_at: z.string().nullable(),
  updated_at: z.string().nullable(),
});

export const learningRoundSchema = z.object({
  iteration_id: z.string(),
  generation_id: z.string(),
  evidence: z.string().nullable(),
  policy: z.string().nullable(),
  stages: z.record(z.string(), z.string()),
  next_stage: z.string().nullable(),
  produced_checkpoint: z.string().nullable(),
  episodes: z.number().int().nonnegative(),
  mean_fitness: z.number().nullable(),
  kill_rate: z.number().nullable(),
  success_rate: z.number().nullable(),
  metrics_source: z.string(),
});
