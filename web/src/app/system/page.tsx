import { SystemDashboard } from "@/components/system/system-dashboard";
import { serverApi } from "@/lib/api/server";
import { publicEnv } from "@/lib/env";

export default async function SystemPage() {
  const api = serverApi();
  const [health, readiness, config, generations] = await Promise.allSettled([
    api.health(),
    api.ready(),
    api.config(),
    api.generations(),
  ]);
  return (
    <SystemDashboard
      health={health.status === "fulfilled" ? health.value : null}
      readiness={readiness.status === "fulfilled" ? readiness.value : null}
      config={config.status === "fulfilled" ? config.value : null}
      generations={generations.status === "fulfilled" ? generations.value : null}
      sample={publicEnv.NEXT_PUBLIC_DATA_MODE === "sample"}
      refreshedAt={new Date().toISOString()}
    />
  );
}
