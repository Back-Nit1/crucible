import { ErrorState } from "@/components/ui/data-state";
import { GenerationDetailView } from "@/components/world/generation-detail";
import { serverApi } from "@/lib/api/server";
import { publicEnv } from "@/lib/env";

export const dynamic = "force-dynamic";

export default async function GenerationPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  let generation = null;
  let message = "The generation could not be loaded.";
  try {
    generation = await serverApi().generation(id);
  } catch (error) {
    message = error instanceof Error ? error.message : message;
  }
  if (!generation) return <ErrorState title="Generation unavailable" message={message} />;
  return <GenerationDetailView generation={generation} sample={publicEnv.NEXT_PUBLIC_DATA_MODE === "sample"} />;
}
