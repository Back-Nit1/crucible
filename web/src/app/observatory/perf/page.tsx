import { CrowdHarness } from "@/components/observatory/crowd-harness";
import { ErrorState } from "@/components/ui/data-state";
import { serverApi } from "@/lib/api/server";
import type { GenerationSnapshot } from "@/lib/api/types";

export const dynamic = "force-dynamic";

export default async function ObservatoryPerfPage() {
  const api = serverApi();
  let snapshot: GenerationSnapshot | null = null;
  let message = "The snapshot could not be loaded.";
  try {
    const id = (await api.generations()).items[0]?.generation_id;
    if (!id) throw new Error("No generation archive is available.");
    snapshot = await api.snapshot(id);
  } catch (error) {
    message = error instanceof Error ? error.message : message;
  }
  return snapshot ? (
    <CrowdHarness snapshot={snapshot} />
  ) : (
    <ErrorState title="Snapshot unavailable" message={message} />
  );
}
