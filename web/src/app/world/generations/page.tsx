import { ErrorState } from "@/components/ui/data-state";
import { PageHeader } from "@/components/ui/page-header";
import { Panel } from "@/components/ui/panel";
import { StatusBadge } from "@/components/ui/status-badge";
import { serverApi } from "@/lib/api/server";
import { publicEnv } from "@/lib/env";
import { shortHash } from "@/lib/records";
import Link from "next/link";

export default async function GenerationsPage() {
  let page = null;
  let message = "Generation data was unavailable.";
  try {
    page = await serverApi().generations(0, 200);
  } catch (error) {
    message = error instanceof Error ? error.message : message;
  }
  if (!page) return <ErrorState message={message} />;
  return (
    <>
        <PageHeader
          eyebrow="World / generation archive"
          title="Every evolutionary run, preserved."
          description="Open a generation to inspect its population, task mix, selection pressure, checkpoints, and curation result."
          actions={<StatusBadge tone={publicEnv.NEXT_PUBLIC_DATA_MODE === "sample" ? "warning" : "positive"}>{publicEnv.NEXT_PUBLIC_DATA_MODE === "sample" ? "Sample data" : "Live API"}</StatusBadge>}
        />
        <Panel className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[780px] text-left text-sm">
              <thead className="border-b border-white/8 bg-white/[0.02] font-mono text-[0.62rem] tracking-[0.1em] text-slate-600 uppercase"><tr><th className="px-5 py-3">Generation</th><th>Status</th><th>Runner</th><th>Population</th><th>Tasks</th><th>Survivors</th><th>Catalog</th></tr></thead>
              <tbody>{page.items.map((generation) => <tr key={generation.generation_id} className="border-b border-white/6"><td className="px-5 py-4"><Link href={`/world/generations/${encodeURIComponent(generation.generation_id)}`} className="font-mono text-xs text-emerald-300 hover:underline">{generation.generation_id}</Link></td><td><StatusBadge tone={generation.status === "completed" ? "positive" : "warning"}>{generation.status}</StatusBadge></td><td>{generation.runner ?? "Not published"}</td><td>{generation.population_size}</td><td>{generation.tasks ?? "N/A"}</td><td>{generation.survivors}</td><td className="font-mono text-xs text-slate-500" title={generation.catalog_hash ?? undefined}>{shortHash(generation.catalog_hash)}</td></tr>)}</tbody>
            </table>
          </div>
        </Panel>
    </>
  );
}
