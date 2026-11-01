import { EpisodeDetailView } from "@/components/episodes/episode-detail";
import { ErrorState } from "@/components/ui/data-state";
import { serverApi } from "@/lib/api/server";
import { publicEnv } from "@/lib/env";

export default async function EpisodePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  let episode = null;
  let message = "The episode could not be loaded.";
  try {
    episode = await serverApi().episode(id);
  } catch (error) {
    message = error instanceof Error ? error.message : message;
  }
  if (!episode) return <ErrorState title="Episode unavailable" message={message} />;
  return <EpisodeDetailView episode={episode} sample={publicEnv.NEXT_PUBLIC_DATA_MODE === "sample"} />;
}
