import { ArrowLeft, Bot, Fingerprint, ShieldAlert } from "lucide-react";
import Link from "next/link";
import type { EpisodeDetail } from "@/lib/api/types";
import { asRecord, at, shortHash, stringAt } from "@/lib/records";
import { ResearchTimeline } from "@/components/agent/research-timeline";
import { MetricCard } from "@/components/ui/metric-card";
import { PageHeader } from "@/components/ui/page-header";
import { Panel, PanelBody, PanelHeader } from "@/components/ui/panel";
import { StatusBadge } from "@/components/ui/status-badge";

function Value({ value }: { value: unknown }) {
  return <pre className="mt-2 overflow-x-auto whitespace-pre-wrap break-words font-mono text-[0.68rem] leading-5 text-slate-400">{JSON.stringify(value, null, 2)}</pre>;
}

export function EpisodeDetailView({ episode, sample }: { episode: EpisodeDetail; sample: boolean }) {
  const score = episode.score_components;
  const genome = episode.genome;
  const scripted = stringAt(genome, "model_checkpoint")?.startsWith("scripted") ?? false;
  const parse = episode.replay.find((step) => step.tool === "parse_intent");
  const paymentRefs = episode.payment_events.flatMap((event) => {
    const refs = asRecord(event).refs;
    return Array.isArray(refs) ? refs.map(String) : [];
  });

  return (
    <>
      <Link href="/episodes" className="mb-5 inline-flex items-center gap-2 text-xs text-slate-500 hover:text-slate-200"><ArrowLeft className="size-3.5" /> Episode explorer</Link>
      <PageHeader eyebrow="Episode / auditable replay" title={episode.episode_id} description={episode.task_text} actions={<><StatusBadge tone={sample ? "warning" : "positive"}>{sample ? "Sample data" : "Live API"}</StatusBadge><StatusBadge tone={episode.killed ? "danger" : "positive"}>{episode.killed ? "Killed" : episode.termination}</StatusBadge></>} />

      {scripted ? <div className="mb-6 rounded-xl border border-amber-800/50 bg-amber-950/20 px-4 py-3 text-sm leading-6 text-amber-100/75"><strong className="text-amber-200">Reference-answer-driven scripted episode.</strong> Use this trace to verify orchestration, not model quality.</div> : null}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-6">
        <MetricCard label="Fitness" value={episode.fitness === null ? "Not scored" : episode.fitness.toFixed(4)} />
        <MetricCard label="Hard gate" value={String(at(score, "gate") ?? "Not measured")} />
        <MetricCard label="Quality" value={String(at(score, "quality") ?? "Not measured")} />
        <MetricCard label="Tool calls" value={episode.tool_call_count} />
        <MetricCard label="Review IDs" value={episode.review_ids_cited.length} />
        <MetricCard label="Payment refs" value={paymentRefs.length} />
      </div>

      <div className="mt-6 grid gap-6 xl:grid-cols-[0.85fr_1.15fr]">
        <div className="space-y-6">
          <Panel><PanelHeader eyebrow="Task" title="Intent and constraints" /><PanelBody><p className="text-sm leading-6 text-slate-300">{episode.task_text}</p><dl className="mt-4 grid grid-cols-2 gap-3 text-xs"><div><dt className="text-slate-600">Category</dt><dd className="mt-1">{episode.category}</dd></div><div><dt className="text-slate-600">Split</dt><dd className="mt-1">{episode.split}</dd></div></dl><div className="mt-4"><p className="font-mono text-[0.62rem] text-slate-600 uppercase">Parsed intent arguments</p><Value value={parse?.arguments ?? "Not exposed"} /></div><p className="mt-4 text-xs text-amber-100/60">Ground-truth constraint objects are not exposed by this endpoint; parsed intent is not relabelled as ground truth.</p></PanelBody></Panel>
          <Panel><PanelHeader eyebrow="Genome" title="Policy and memory" action={<Bot className="size-4 text-cyan-300" />} /><PanelBody><Value value={genome} /><p className="mt-4 text-xs text-slate-500">Retrieved memory context content and provenance are not exposed in this response. Only genome memory settings are shown.</p></PanelBody></Panel>
          <Panel><PanelHeader eyebrow="Provenance" title="Pinned identities" action={<Fingerprint className="size-4 text-slate-500" />} /><PanelBody className="space-y-3 text-xs"><div><p className="text-slate-600">Catalog hash</p><p className="mt-1 font-mono" title={episode.catalog_hash ?? undefined}>{shortHash(episode.catalog_hash)}</p></div><div><p className="text-slate-600">Model checkpoint</p><p className="mt-1">{stringAt(genome, "model_checkpoint") ?? "Not published"}</p></div><div><p className="text-slate-600">Prompt variant</p><p className="mt-1">{stringAt(genome, "system_prompt_variant") ?? "Not published"}</p></div><div><p className="text-slate-600">Raw output hash</p><p className="mt-1 text-slate-500">Not published (raw output is never displayed)</p></div></PanelBody></Panel>
        </div>

        <div className="space-y-6">
          <Panel><PanelHeader eyebrow="Replay" title="Ordered tool calls" /><PanelBody><ResearchTimeline steps={episode.replay} /><details className="mt-4 border-t border-white/8 pt-4"><summary className="text-xs font-semibold text-slate-300">Arguments and result references</summary><div className="mt-4 space-y-4">{episode.replay.map((step) => <article key={step.sequence} className="rounded-xl border border-white/8 p-3"><p className="font-mono text-xs text-emerald-300">#{step.sequence} {step.tool}</p><Value value={{ arguments: step.arguments, result_references: step.result_references, error_code: step.error_code }} /></article>)}</div></details></PanelBody></Panel>
          {episode.kills.length ? <Panel className="border-rose-800/40"><PanelHeader eyebrow="Kill evidence" title={`${episode.kills.length} rule${episode.kills.length === 1 ? "" : "s"} fired`} action={<ShieldAlert className="size-4 text-rose-300" />} /><PanelBody className="space-y-4">{episode.kills.map((kill) => <article key={`${kill.rule_id}-${kill.rule_version}`}><div className="flex items-center gap-2"><p className="font-mono text-xs text-rose-200">{kill.rule_id}</p><span className="text-xs text-slate-600">v{kill.rule_version}</span></div><p className="mt-2 text-xs text-slate-400">{kill.description}</p><ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-rose-100/65">{kill.evidence.map((evidence) => <li key={evidence}>{evidence}</li>)}</ul></article>)}</PanelBody></Panel> : null}
          <Panel><PanelHeader eyebrow="Scoring" title="Components and hard gate" /><PanelBody><Value value={score} /></PanelBody></Panel>
          <Panel><PanelHeader eyebrow="Decision & payment" title="Outcome ledger" /><PanelBody><p className="text-sm leading-6 text-slate-300">{episode.final_answer}</p><div className="mt-4"><p className="font-mono text-[0.62rem] text-slate-600 uppercase">Payment events</p><Value value={episode.payment_events.length ? episode.payment_events : "No payment events"} /></div><p className="mt-4 text-xs text-slate-500">Quote breakdown and receipt fields appear only when present in recorded payment events. Nothing is reconstructed.</p></PanelBody></Panel>
        </div>
      </div>
    </>
  );
}
