import { AgentWorkspace } from "@/components/agent/agent-workspace";
import { getSample } from "@/lib/api/samples";
import { episodeDetailSchema } from "@/lib/api/schemas";
import type { AgentRunResult } from "@/lib/api/types";
import { publicEnv } from "@/lib/env";

function sampleNoMatch(): AgentRunResult | null {
  if (publicEnv.NEXT_PUBLIC_DATA_MODE !== "sample") return null;
  const episode = episodeDetailSchema.parse(getSample("world_episode_detail").body);
  const intentStep = episode.replay.find((step) => step.tool === "parse_intent");
  return {
    parsed_intent: intentStep?.arguments ?? {},
    steps: episode.replay,
    picks: [],
    no_match: episode.termination === "no_match",
    closest_product_id:
      (episode.replay.find((step) => step.tool === "report_no_match")?.arguments
        .closest_product_id as string | undefined) ?? null,
    assumptions:
      (intentStep?.arguments.assumptions as string[] | undefined) ?? ["No assumptions returned"],
    final_answer: episode.final_answer,
    model: String(episode.genome.model_checkpoint ?? "scripted"),
    latency_ms: null,
    cost_usd: null,
  };
}

export default function HomePage() {
  return <AgentWorkspace sampleNoMatch={sampleNoMatch()} />;
}
