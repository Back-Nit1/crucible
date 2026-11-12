import type { z } from "zod";
import type {
  agentRunResultSchema,
  buyerEventSchema,
  buyerRunSchema,
  configSchema,
  confirmResultSchema,
  documentSchema,
  episodeDetailSchema,
  episodeSchema,
  generationDetailSchema,
  generationSchema,
  healthSchema,
  killLogSchema,
  killRuleSchema,
  leaderboardSchema,
  ledgerRowSchema,
  pickSchema,
  proposeResultSchema,
  loopStatusSchema,
  readySchema,
  replayStepSchema,
  crowdEpisodeSchema,
  learningRoundSchema,
  generationChoiceSchema,
  trainingRunSchema,
} from "./schemas";

export type Page<T> = { items: T[]; total: number; offset: number; limit: number };
export type Generation = z.infer<typeof generationSchema>;
export type GenerationDetail = z.infer<typeof generationDetailSchema>;
export type Episode = z.infer<typeof episodeSchema>;
export type EpisodeDetail = z.infer<typeof episodeDetailSchema>;
export type ReplayStep = z.infer<typeof replayStepSchema>;
export type LeaderboardRow = z.infer<typeof leaderboardSchema>;
export type KillLog = z.infer<typeof killLogSchema>;
export type KillRule = z.infer<typeof killRuleSchema>;
export type ApiDocument = z.infer<typeof documentSchema>;
export type LedgerRow = z.infer<typeof ledgerRowSchema>;
export type Health = z.infer<typeof healthSchema>;
export type Readiness = z.infer<typeof readySchema>;
export type LoopStatus = z.infer<typeof loopStatusSchema>;
export type PublicConfig = z.infer<typeof configSchema>;
export type AgentRunResult = z.infer<typeof agentRunResultSchema>;
export type ProductPick = z.infer<typeof pickSchema>;
export type ProposeResult = z.infer<typeof proposeResultSchema>;
export type ConfirmResult = z.infer<typeof confirmResultSchema>;
export type BuyerEvent = z.infer<typeof buyerEventSchema>;
export type BuyerRun = z.infer<typeof buyerRunSchema>;
export type BuyerEventOf<T extends BuyerEvent["type"]> = Extract<BuyerEvent, { type: T }>;

export type EpisodeQuery = {
  generation_id?: string;
  agent_id?: string;
  split?: string;
  category?: string;
  killed?: boolean;
  kill_rule_id?: string;
  min_fitness?: number;
  max_fitness?: number;
  sort?:
    | "fitness"
    | "-fitness"
    | "episode_id"
    | "-episode_id"
    | "agent_id"
    | "-agent_id"
    | "generation_id"
    | "-generation_id"
    | "category"
    | "-category"
    | "killed"
    | "-killed";
  offset?: number;
  limit?: number;
};

export type ApiErrorCode =
  | "model_unavailable"
  | "world_data_unavailable"
  | "provider_unavailable"
  | "budget_exceeded"
  | "price_mismatch"
  | "out_of_stock"
  | "confirmation_required"
  | "quote_stale"
  | "quote_changed"
  | "quote_incomplete"
  | "payment_failed"
  | "invalid_request"
  | "internal_error"
  | string;
export type CrowdEpisode = z.infer<typeof crowdEpisodeSchema>;
export type GenerationChoice = z.infer<typeof generationChoiceSchema>;
export type TrainingRun = z.infer<typeof trainingRunSchema>;
export type LearningRound = z.infer<typeof learningRoundSchema>;
