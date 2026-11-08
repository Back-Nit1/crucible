import type { DataMode } from "@/lib/env";
import { getSample } from "./samples";
import {
  agentRunResultSchema,
  apiErrorSchema,
  buyerRunSchema,
  configSchema,
  confirmResultSchema,
  documentSchema,
  episodeDetailSchema,
  episodeSchema,
  generationDetailSchema,
  generationSnapshotSchema,
  generationSchema,
  healthSchema,
  killLogSchema,
  killRuleSchema,
  leaderboardSchema,
  ledgerRowSchema,
  pageSchema,
  proposeResultSchema,
  loopStatusSchema,
  readySchema,
} from "./schemas";
import type { EpisodeQuery } from "./types";

export class ApiError extends Error {
  constructor(
    readonly code: string,
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const sampleByPath = {
  "/health": "health",
  "/world/generations": "world_generations",
  "/world/episodes": "world_episodes",
  "/world/leaderboard": "world_leaderboard",
  "/world/kills": "world_kills",
  "/world/kill-rules": "world_kill_rules",
  "/models/evaluations": "models_evaluations",
  "/models/checkpoints": "models_checkpoints",
  "/payments/ledger": "payments_ledger",
} as const;

type SamplePath = keyof typeof sampleByPath;

function withQuery(path: string, query: Record<string, unknown> = {}) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  }
  const suffix = search.toString();
  return suffix ? `${path}?${suffix}` : path;
}

export class CrucibleApi {
  constructor(
    private readonly baseUrl: string,
    readonly mode: DataMode,
    // Arrow, not a bare `fetch`: calling the global as a method of this class throws "Illegal invocation" in browsers.
    private readonly fetcher: typeof fetch = (input, init) => fetch(input, init),
  ) {}

  private async request(path: string, init?: RequestInit): Promise<unknown> {
    if (this.mode === "sample") {
      const plainPath = path.split("?")[0] ?? path;
      if (init?.method === "POST" && plainPath === "/agent/runs") {
        return getSample("agent_run_started").body;
      }
      if (init?.method === "POST" && /^\/agent\/runs\/[^/]+\/confirm$/.test(plainPath)) {
        return getSample("agent_run_receipt").body;
      }
      if ((!init?.method || init.method === "GET") && /^\/agent\/runs\/[^/]+$/.test(plainPath)) {
        return getSample("agent_run_poll").body;
      }
      if (init?.method && init.method !== "GET") {
        throw new ApiError("sample_read_only", "Sample data is read-only.", 405);
      }
      if (/^\/world\/generations\/[^/]+\/snapshot$/.test(plainPath)) {
        return (await import("@/generated/snapshot-sample.json")).default.body; // own chunk: large
      }
      if (plainPath.startsWith("/world/generations/") && plainPath !== "/world/generations") {
        return getSample("world_generation_detail").body;
      }
      if (plainPath.startsWith("/world/episodes/") && plainPath !== "/world/episodes") {
        return getSample("world_episode_detail").body;
      }
      const fixture = sampleByPath[plainPath as SamplePath];
      if (!fixture) {
        throw new ApiError(
          "sample_unavailable",
          `No sanitized sample exists for ${plainPath}.`,
          404,
        );
      }
      return getSample(fixture).body;
    }

    const response = await this.fetcher(new URL(path, this.baseUrl), {
      ...init,
      headers: { Accept: "application/json", "Content-Type": "application/json", ...init?.headers },
      cache: init?.method && init.method !== "GET" ? "no-store" : "no-cache",
    });
    const body: unknown = await response.json().catch(() => null);
    if (!response.ok) {
      const parsed = apiErrorSchema.safeParse(body);
      throw new ApiError(
        parsed.success ? parsed.data.error.code : "invalid_error_response",
        parsed.success ? parsed.data.error.message : `API request failed (${response.status}).`,
        response.status,
      );
    }
    return body;
  }

  health = async () => healthSchema.parse(await this.request("/health"));
  ready = async () => readySchema.parse(await this.request("/ready"));
  config = async () => configSchema.parse(await this.request("/config"));
  loopStatus = async () => loopStatusSchema.parse(await this.request("/loop/status"));
  generations = async (offset = 0, limit = 50) =>
    pageSchema(generationSchema).parse(
      await this.request(withQuery("/world/generations", { offset, limit })),
    );
  generation = async (id: string) =>
    generationDetailSchema.parse(
      await this.request(`/world/generations/${encodeURIComponent(id)}`),
    );
  snapshot = async (id: string) =>
    generationSnapshotSchema.parse(
      await this.request(`/world/generations/${encodeURIComponent(id)}/snapshot`),
    );
  episodes = async (query: EpisodeQuery = {}) =>
    pageSchema(episodeSchema).parse(await this.request(withQuery("/world/episodes", query)));
  episode = async (id: string) =>
    episodeDetailSchema.parse(await this.request(`/world/episodes/${encodeURIComponent(id)}`));
  leaderboard = async (generationId?: string) =>
    pageSchema(leaderboardSchema).parse(
      await this.request(withQuery("/world/leaderboard", { generation_id: generationId })),
    );
  kills = async (generationId?: string, ruleId?: string) =>
    pageSchema(killLogSchema).parse(
      await this.request(
        withQuery("/world/kills", { generation_id: generationId, rule_id: ruleId, limit: 200 }),
      ),
    );
  killRules = async () => killRuleSchema.array().parse(await this.request("/world/kill-rules"));
  evaluations = async () =>
    pageSchema(documentSchema).parse(await this.request("/models/evaluations"));
  checkpoints = async () =>
    pageSchema(documentSchema).parse(await this.request("/models/checkpoints"));
  ledger = async (generationId?: string) =>
    pageSchema(ledgerRowSchema).parse(
      await this.request(
        withQuery("/payments/ledger", { generation_id: generationId, limit: 200 }),
      ),
    );
  runAgent = async (message: string, mode: "trained" | "base" | "scripted" = "trained") =>
    agentRunResultSchema.parse(
      await this.request("/agent/run", {
        method: "POST",
        body: JSON.stringify({ message, mode }),
      }),
    );
  startBuyerRun = async (message: string, budget?: string, requestId?: string) =>
    buyerRunSchema.parse(
      await this.request("/agent/runs", {
        method: "POST",
        body: JSON.stringify({ message, budget, request_id: requestId }),
      }),
    );
  pollBuyerRun = async (runId: string, after = -1) =>
    buyerRunSchema.parse(
      await this.request(withQuery(`/agent/runs/${encodeURIComponent(runId)}`, { after })),
    );
  confirmBuyerRun = async (runId: string, pendingOrderId: string, userConfirmed: boolean) =>
    buyerRunSchema.parse(
      await this.request(`/agent/runs/${encodeURIComponent(runId)}/confirm`, {
        method: "POST",
        body: JSON.stringify({ pending_order_id: pendingOrderId, user_confirmed: userConfirmed }),
      }),
    );
  propose = async (input: {
    task_id: string;
    agent_id: string;
    product_id: string;
    variant: string;
    expected_total: string;
    budget_cap: string;
  }) =>
    proposeResultSchema.parse(
      await this.request("/purchase/propose", { method: "POST", body: JSON.stringify(input) }),
    );
  confirm = async (pendingOrderId: string, userConfirmed: boolean) =>
    confirmResultSchema.parse(
      await this.request("/purchase/confirm", {
        method: "POST",
        body: JSON.stringify({ pending_order_id: pendingOrderId, user_confirmed: userConfirmed }),
      }),
    );
}
