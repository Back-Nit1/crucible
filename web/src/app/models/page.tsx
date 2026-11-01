import { ModelDashboard } from "@/components/models/model-dashboard";
import { ErrorState } from "@/components/ui/data-state";
import { serverApi } from "@/lib/api/server";
import { publicEnv } from "@/lib/env";

export const dynamic = "force-dynamic";

export default async function ModelsPage() {
  const api = serverApi();
  let data = null;
  let message = "Model registry data could not be loaded.";
  try {
    const [evaluations, checkpoints] = await Promise.all([api.evaluations(), api.checkpoints()]);
    data = { evaluations, checkpoints };
  } catch (error) {
    message = error instanceof Error ? error.message : message;
  }
  if (!data) return <ErrorState title="Model data unavailable" message={message} />;
  return <ModelDashboard {...data} sample={publicEnv.NEXT_PUBLIC_DATA_MODE === "sample"} />;
}
