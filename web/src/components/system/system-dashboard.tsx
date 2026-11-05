import { Activity, Database, RefreshCw, Server, ShieldCheck, TriangleAlert } from "lucide-react";
import type { Generation, Health, LoopStatus, Page, PublicConfig, Readiness } from "@/lib/api/types";
import { shortHash } from "@/lib/records";
import { PageHeader } from "@/components/ui/page-header";
import { Panel, PanelBody, PanelHeader } from "@/components/ui/panel";
import { StatusBadge, type StatusTone } from "@/components/ui/status-badge";

function Check({ label, value, missing = false }: { label: string; value?: boolean; missing?: boolean }) {
  const tone: StatusTone = missing ? "neutral" : value ? "positive" : "danger";
  return <div className="flex items-center justify-between gap-3 border-b border-white/7 py-3"><span className="text-sm text-slate-400">{label}</span><StatusBadge tone={tone}>{missing ? "Not exposed" : value ? "Available" : "Degraded"}</StatusBadge></div>;
}

export function SystemDashboard({
  health,
  readiness,
  config,
  generations,
  loop = null,
  sample,
  refreshedAt,
}: {
  health: Health | null;
  readiness: Readiness | null;
  config: PublicConfig | null;
  generations: Page<Generation> | null;
  loop?: LoopStatus | null;
  sample: boolean;
  refreshedAt: string;
}) {
  const current = generations?.items[0];
  const degraded = !health || (!sample && (!readiness || readiness.status !== "ok"));
  return (
    <>
      <PageHeader
        eyebrow="System / operational readiness"
        title="A public status view with nothing secret to leak."
        description="API liveness, configured dependencies, public deployment settings, catalog identity, and actionable degraded states."
        actions={<><a href="/system" className="inline-flex items-center gap-2 rounded-lg border border-white/10 px-3 py-2 text-xs text-slate-300"><RefreshCw className="size-3.5" /> Refresh</a><StatusBadge tone={sample ? "warning" : degraded ? "danger" : "positive"} dot>{sample ? "Sample data" : degraded ? "Degraded" : "Operational"}</StatusBadge></>}
      />

      {degraded ? <div role="alert" className="mb-6 flex gap-3 rounded-xl border border-rose-800/50 bg-rose-950/20 p-4"><TriangleAlert className="mt-0.5 size-5 shrink-0 text-rose-300" /><div><p className="text-sm font-semibold text-rose-100">Deployment is not fully ready</p><p className="mt-1 text-xs leading-5 text-rose-200/65">Check the API origin, then verify server-side Elastic, model, and payment environment configuration. Secret values belong only in the API deployment.</p></div></div> : null}

      <div className="grid gap-6 lg:grid-cols-3">
        <Panel><PanelHeader eyebrow="API" title="Health and readiness" action={<Activity className="size-4 text-emerald-300" />} /><PanelBody><Check label="Liveness" value={health?.status === "ok"} missing={!health} /><Check label="Elastic" value={readiness?.checks.elastic_configured} missing={!readiness} /><Check label="Model runner" value={readiness?.checks.model_configured} missing={!readiness} /><Check label="PayPal sandbox" value={readiness?.checks.paypal_sandbox_configured} missing={!readiness} /><div className="mt-4 text-xs text-slate-600">API version: {readiness?.version ?? config?.version ?? "Not exposed"}</div></PanelBody></Panel>
        <Panel><PanelHeader eyebrow="Deployment" title="Public configuration" action={<Server className="size-4 text-cyan-300" />} /><PanelBody className="space-y-4 text-sm"><div><p className="text-xs text-slate-600">Active provider</p><p className="mt-1 text-slate-300">{config?.catalog ?? "Not exposed in sample"}</p></div><div><p className="text-xs text-slate-600">Payment backend</p><p className="mt-1 text-slate-300">{config?.payments?.toUpperCase() ?? "Not exposed"}</p></div><div><p className="text-xs text-slate-600">All-in quote required</p><p className="mt-1 text-slate-300">{config ? (config.require_all_in_quote ? "Yes" : "No") : "Not exposed"}</p></div><div><p className="text-xs text-slate-600">Scheduler status</p><p className="mt-1 text-slate-500">Not exposed by public API</p></div></PanelBody></Panel>
        <Panel><PanelHeader eyebrow="Data" title="Catalog provenance" action={<Database className="size-4 text-amber-300" />} /><PanelBody className="space-y-4 text-sm"><div><p className="text-xs text-slate-600">Manifest hash</p><p className="mt-1 font-mono text-xs text-slate-300" title={current?.catalog_hash ?? undefined}>{shortHash(current?.catalog_hash)}</p></div><div><p className="text-xs text-slate-600">Snapshot as of</p><p className="mt-1 text-slate-300">{config?.snapshot_as_of ?? "Not exposed"}</p></div><div><p className="text-xs text-slate-600">Data mode</p><p className="mt-1 text-slate-300">{sample ? "Sanitized static API samples" : "Live operational API"}</p></div><div><p className="text-xs text-slate-600">Notice</p><p className="mt-1 text-xs leading-5 text-slate-500">{config?.data_notice ?? "No public configuration sample was supplied."}</p></div></PanelBody></Panel>
      </div>

      <LoopPanel loop={loop} />

      <Panel className="mt-6"><PanelHeader eyebrow="Security boundary" title="Browser-visible configuration" action={<ShieldCheck className="size-4 text-emerald-300" />} /><PanelBody><p className="text-sm leading-6 text-slate-400">This page consumes booleans, provider labels, version strings, and manifest identity only. Elastic keys, PayPal OAuth credentials, sandbox buyer credentials, Modal tokens, and catalog-provider secrets are neither requested nor rendered.</p><p className="mt-4 font-mono text-[0.65rem] text-slate-600">Last refresh: {refreshedAt}</p></PanelBody></Panel>
    </>
  );
}

const stageTone: Record<string, StatusTone> = { done: "positive", blocked: "warning", paused: "info", refused: "danger", failed: "danger" };

function LoopPanel({ loop }: { loop: LoopStatus | null }) {
  return (
    <Panel className="mt-6">
      <PanelHeader eyebrow="Expert iteration" title="Training loop status" action={loop?.kill_switch ? <StatusBadge tone="danger">Kill switch set</StatusBadge> : <RefreshCw className="size-4 text-cyan-300" />} />
      <PanelBody className="space-y-4">
        {!loop ? <p className="text-sm text-slate-500">Not exposed</p> : loop.iterations.length === 0 ? <p className="text-sm text-slate-500">No iterations yet</p> : loop.iterations.map((it) => (
          <div key={it.iteration_id} className="border-b border-white/7 pb-3">
            <div className="flex items-center justify-between gap-3"><span className="font-mono text-sm text-slate-300">{it.iteration_id}</span><span className="text-xs text-slate-500">{it.next_stage ? `next: ${it.next_stage}` : "complete"}</span></div>
            <div className="mt-2 flex flex-wrap gap-2">{it.stages.map((s) => <StatusBadge key={s.stage} tone={stageTone[s.status] ?? "neutral"}>{`${s.stage}: ${s.status}`}</StatusBadge>)}</div>
            {it.stages.filter((s) => s.missing?.length).map((s) => <p key={s.stage} className="mt-2 text-xs text-amber-200/80">{`${s.stage} needs ${s.missing?.join(", ")}`}</p>)}
            {it.stages.some((s) => s.evidence?.startsWith("pipeline_evidence")) ? <p className="mt-2 text-xs text-slate-500">Dry run: scripted pipeline evidence, not model results.</p> : null}
          </div>
        ))}
      </PanelBody>
    </Panel>
  );
}
