import { EpisodeGrid } from "@/components/episodes/episode-grid";
import { PageHeader } from "@/components/ui/page-header";
import { StatusBadge } from "@/components/ui/status-badge";
import { publicEnv } from "@/lib/env";

export default function EpisodesPage() {
  return (
    <>
      <PageHeader
        eyebrow="World / episode explorer"
        title="Interrogate every decision trace."
        description="Filter and sort operational episodes, then open the ordered replay, score evidence, safety rules, and payment boundary."
        actions={
          <StatusBadge tone={publicEnv.NEXT_PUBLIC_DATA_MODE === "sample" ? "warning" : "positive"}>
            {publicEnv.NEXT_PUBLIC_DATA_MODE === "sample" ? "Sample data" : "Live API"}
          </StatusBadge>
        }
      />
      <EpisodeGrid />
    </>
  );
}
