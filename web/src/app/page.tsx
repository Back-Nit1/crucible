import { AgentWorkspace } from "@/components/agent/agent-workspace";
import { getSample } from "@/lib/api/samples";
import { buyerRunSchema } from "@/lib/api/schemas";
import type { BuyerRun } from "@/lib/api/types";
import { publicEnv } from "@/lib/env";

function sample(name: "agent_run_started" | "agent_run_no_match"): BuyerRun | null {
  if (publicEnv.NEXT_PUBLIC_DATA_MODE !== "sample") return null;
  return buyerRunSchema.parse(getSample(name).body);
}

export default function HomePage() {
  return (
    <AgentWorkspace
      sampleRun={sample("agent_run_started")}
      sampleNoMatch={sample("agent_run_no_match")}
    />
  );
}
