import { GitMerge, Scale, ShieldAlert } from "lucide-react";
import Link from "next/link";
import type { GenerationDetail, KillLog, KillRule, Page } from "@/lib/api/types";
import { asRecord, at, numberAt, stringAt } from "@/lib/records";
import { PageHeader } from "@/components/ui/page-header";
import { Panel, PanelBody, PanelHeader } from "@/components/ui/panel";
import { StatusBadge } from "@/components/ui/status-badge";

export function SafetyDashboard({ rules, kills, generation, sample }: { rules: KillRule[]; kills: Page<KillLog>; generation: GenerationDetail; sample: boolean }) {
  const byEpisode = Map.groupBy(kills.items, (kill) => kill.episode_id);
  const proposalsRaw = at(generation.summary, "loophole_hunter_proposals");
  const proposals = Array.isArray(proposalsRaw) ? proposalsRaw.map(asRecord) : [];
  return (
    <>
      <PageHeader eyebrow="World / safety registry" title="Kill rules are evidence, not folklore." description="Every enabled rule is versioned. Every kill links to an episode and reproducing evidence. Loophole proposals remain inert until confirmed." actions={<StatusBadge tone={sample ? "warning" : "positive"}>{sample ? "Sample data" : "Live API"}</StatusBadge>} />
      <div className="grid gap-6 xl:grid-cols-[0.8fr_1.2fr]">
        <Panel>
          <PanelHeader eyebrow="Rule timeline" title={`${rules.length} registered rules`} action={<Scale className="size-4 text-slate-500" />} />
          <PanelBody className="space-y-5">
            {rules.map((rule) => <article key={rule.rule_id} className="relative border-l border-white/12 pl-5"><span className="absolute top-1 -left-1 size-2 rounded-full bg-rose-300" /><div className="flex flex-wrap items-center gap-2"><p className="font-mono text-xs text-rose-200">{rule.rule_id}</p><StatusBadge tone={rule.enabled ? "danger" : "neutral"}>{rule.enabled ? "Enabled" : "Disabled"}</StatusBadge></div><p className="mt-2 text-xs leading-5 text-slate-400">{rule.description}</p><div className="mt-2 flex flex-wrap gap-3 text-[0.65rem] text-slate-600"><span>{rule.added_on}</span><span>version {rule.version}</span><span>{rule.kills} co-fired kills</span><span>hash not exposed</span></div></article>)}
          </PanelBody>
        </Panel>
        <Panel>
          <PanelHeader eyebrow="Kill log" title="Evidence and co-fired rules" action={<ShieldAlert className="size-4 text-rose-300" />} />
          <PanelBody className="space-y-4">
            {[...byEpisode.entries()].map(([episodeId, episodeKills]) => <article key={episodeId} className="rounded-xl border border-white/8 bg-black/15 p-4"><div className="flex flex-col justify-between gap-3 sm:flex-row"><Link href={`/episodes/${encodeURIComponent(episodeId)}`} className="break-all font-mono text-xs text-emerald-300 hover:underline">{episodeId}</Link><StatusBadge tone={episodeKills.length > 1 ? "warning" : "danger"}>{episodeKills.length} rule{episodeKills.length === 1 ? "" : "s"} fired</StatusBadge></div><div className="mt-4 space-y-4">{episodeKills.map((kill) => <div key={`${kill.rule_id}-${kill.rule_version}`}><p className="font-mono text-xs text-rose-200">{kill.rule_id} · v{kill.rule_version}</p><ul className="mt-2 list-disc space-y-1 pl-5 text-xs leading-5 text-slate-500">{kill.evidence.map((evidence) => <li key={evidence}>{evidence}</li>)}</ul></div>)}</div></article>)}
          </PanelBody>
        </Panel>
      </div>
      <Panel className="mt-6">
        <PanelHeader eyebrow="Loophole Hunter" title="Proposal and confirmation state" action={<GitMerge className="size-4 text-amber-300" />} />
        <PanelBody className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {proposals.map((proposal) => <article key={stringAt(proposal, "rule_id") ?? JSON.stringify(proposal)} className="rounded-xl border border-amber-800/35 bg-amber-950/10 p-4"><div className="flex items-center justify-between gap-2"><p className="font-mono text-xs text-amber-200">{stringAt(proposal, "rule_id") ?? "Unnamed"}</p><StatusBadge tone="warning">{stringAt(proposal, "state") ?? "Unknown"}</StatusBadge></div><p className="mt-3 text-xs text-slate-500">Affected episodes: {numberAt(proposal, "episodes") ?? "Not published"}</p><ul className="mt-3 list-disc space-y-1 pl-5 text-xs leading-5 text-slate-500">{(Array.isArray(at(proposal, "evidence")) ? at(proposal, "evidence") as unknown[] : []).map(String).map((evidence) => <li key={evidence}>{evidence}</li>)}</ul><p className="mt-4 border-t border-amber-800/20 pt-3 text-[0.65rem] text-amber-200/60">Proposal only. No rule is enabled by this state.</p></article>)}
        </PanelBody>
      </Panel>
    </>
  );
}
