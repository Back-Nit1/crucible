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
