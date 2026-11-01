import { ErrorState } from "@/components/ui/data-state";
import { WorldDashboard } from "@/components/world/world-dashboard";
import { serverApi } from "@/lib/api/server";
import { publicEnv } from "@/lib/env";

export default async function WorldPage() {
  const api = serverApi();
  let data = null;
  let message = "The world API did not return valid data.";
  try {
    const generations = await api.generations();
    const first = generations.items[0];
    if (!first) {
      message = "The world API returned an empty generation archive.";
    } else {
      const [current, leaderboard, killRules] = await Promise.all([
        api.generation(first.generation_id),
        api.leaderboard(first.generation_id),
        api.killRules(),
      ]);
      data = { generations, current, leaderboard, killRules };
    }
  } catch (error) {
    message = error instanceof Error ? error.message : message;
  }
  if (!data) return <ErrorState title="World unavailable" message={message} />;
  return <WorldDashboard {...data} sample={publicEnv.NEXT_PUBLIC_DATA_MODE === "sample"} />;
}
