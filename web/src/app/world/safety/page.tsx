import { SafetyDashboard } from "@/components/safety/safety-dashboard";
import { ErrorState } from "@/components/ui/data-state";
import { serverApi } from "@/lib/api/server";
import { publicEnv } from "@/lib/env";

export const dynamic = "force-dynamic";

export default async function SafetyPage() {
  const api = serverApi();
  let data = null;
  let message = "Safety records could not be loaded.";
  try {
    const generations = await api.generations();
    const generationId = generations.items[0]?.generation_id;
    if (generationId) {
      const [rules, kills, generation] = await Promise.all([api.killRules(), api.kills(generationId), api.generation(generationId)]);
      data = { rules, kills, generation };
    } else message = "No generation exists for the safety registry.";
  } catch (error) {
    message = error instanceof Error ? error.message : message;
  }
  if (!data) return <ErrorState title="Safety registry unavailable" message={message} />;
  return <SafetyDashboard {...data} sample={publicEnv.NEXT_PUBLIC_DATA_MODE === "sample"} />;
}
