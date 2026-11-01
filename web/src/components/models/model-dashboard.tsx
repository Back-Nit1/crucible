import { BrainCircuit, CheckCircle2, CircleDashed, Clock, Coins, Fingerprint } from "lucide-react";
import type { ApiDocument, Page } from "@/lib/api/types";
import { asRecord, at, numberAt, shortHash, stringAt } from "@/lib/records";
import { EmptyState } from "@/components/ui/data-state";
import { PageHeader } from "@/components/ui/page-header";
import { Panel, PanelBody, PanelHeader } from "@/components/ui/panel";
import { StatusBadge } from "@/components/ui/status-badge";

const metrics = [
  ["success_rate", "Success"],
  ["hard_constraint_satisfaction", "Hard constraints"],
  ["hallucination_rate", "Hallucination"],
  ["correct_refusal_rate", "Correct refusal"],
  ["wrong_refusal_rate", "Wrong refusal"],
  ["budget_violation_rate", "Budget violations"],
  ["intent_extraction_accuracy", "Intent accuracy"],
  ["review_grounding_rate", "Review grounding"],
  ["review_trap_accuracy", "Review traps"],
  ["persona_relevant_review_recall", "Persona review recall"],
  ["pass_at_k", "Pass@k"],
  ["held_out_category_performance", "Held-out categories"],
] as const;

type MetricView = { measured: boolean; display: string; detail: string };

export function readMetric(data: Record<string, unknown>, name: string): MetricView {
  const raw = asRecord(at(data, "metrics"))[name] ?? data[name];
  if (raw === null || raw === undefined) return { measured: false, display: "Not measured", detail: "No numerator / denominator published" };
  if (typeof raw === "number") return { measured: true, display: `${(raw * 100).toFixed(1)}%`, detail: "Denominator not published" };
  const record = asRecord(raw);
  const value = numberAt(record, "value");
  const numerator = numberAt(record, "numerator");
  const denominator = numberAt(record, "denominator");
  const excluded = numberAt(record, "excluded");
  const display = value === null ? "Not measured" : `${(value * 100).toFixed(1)}%`;
  const denominatorDetail = numerator === null || denominator === null ? "Denominator not published" : `${numerator} / ${denominator}`;
  return { measured: value !== null, display, detail: `${denominatorDetail}${excluded === null ? "" : ` · ${excluded} excluded`}` };
}

function EvaluationCard({ evaluation }: { evaluation: ApiDocument }) {
  const data = evaluation.data;
  const contender = stringAt(data, "contender") ?? stringAt(data, "name") ?? evaluation.id;
  const status = stringAt(data, "status") ?? "completed";
  return (
    <Panel className="overflow-hidden">
      <PanelHeader eyebrow="Contender" title={contender} action={<StatusBadge tone={status === "completed" ? "positive" : "warning"}>{status}</StatusBadge>} />
      <PanelBody>
        <div className="mb-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div><p className="text-xs text-slate-600">Checkpoint</p><p className="mt-1 font-mono text-xs text-slate-300">{stringAt(data, "checkpoint") ?? stringAt(data, "model_version") ?? "Not published"}</p></div>
          <div><p className="text-xs text-slate-600">Task manifest</p><p className="mt-1 font-mono text-xs text-slate-300" title={stringAt(data, "task_set_hash") ?? undefined}>{shortHash(stringAt(data, "task_set_hash"))}</p></div>
          <div><p className="text-xs text-slate-600">Catalog</p><p className="mt-1 font-mono text-xs text-slate-300" title={stringAt(data, "catalog_hash") ?? undefined}>{shortHash(stringAt(data, "catalog_hash"))}</p></div>
          <div><p className="text-xs text-slate-600">Judge</p><p className="mt-1 font-mono text-xs text-slate-300">{stringAt(data, "judge_version") ?? "Not used / published"}</p></div>
        </div>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {metrics.map(([name, label]) => {
            const metric = readMetric(data, name);
            return <article key={name} className="rounded-xl border border-white/8 bg-black/15 p-3"><div className="flex items-center justify-between gap-2"><p className="text-xs text-slate-500">{label}</p>{metric.measured ? <CheckCircle2 className="size-3.5 text-emerald-300" /> : <CircleDashed className="size-3.5 text-slate-600" />}</div><p className={`mt-2 text-lg font-semibold tabular-nums ${metric.measured ? "text-slate-100" : "text-slate-500"}`}>{metric.display}</p><p className="mt-1 text-[0.65rem] text-slate-600">{metric.detail}</p></article>;
          })}
        </div>
        <div className="mt-5 grid gap-3 sm:grid-cols-3">
          <div className="rounded-xl border border-white/8 p-3"><Clock className="size-4 text-cyan-300" /><p className="mt-2 text-xs text-slate-600">Latency</p><p className="mt-1 text-sm">{numberAt(data, "latency_ms") === null ? "Not measured" : `${numberAt(data, "latency_ms")} ms`}</p></div>
          <div className="rounded-xl border border-white/8 p-3"><Coins className="size-4 text-amber-300" /><p className="mt-2 text-xs text-slate-600">Cost / task</p><p className="mt-1 text-sm">{numberAt(data, "cost_per_task_usd") === null ? "Not measured" : `$${numberAt(data, "cost_per_task_usd")}`}</p></div>
          <div className="rounded-xl border border-white/8 p-3"><Fingerprint className="size-4 text-slate-400" /><p className="mt-2 text-xs text-slate-600">Variance across seeds</p><p className="mt-1 text-sm">{numberAt(data, "variance") ?? "Not measured"}</p></div>
        </div>
      </PanelBody>
    </Panel>
  );
}

export function ModelDashboard({ evaluations, checkpoints, sample }: { evaluations: Page<ApiDocument>; checkpoints: Page<ApiDocument>; sample: boolean }) {
  const taskHashes = new Set(evaluations.items.map((item) => stringAt(item.data, "task_set_hash")).filter(Boolean));
  const seedSets = new Set(evaluations.items.map((item) => JSON.stringify(at(item.data, "seeds") ?? null)));
  const comparable = evaluations.items.length > 1 && taskHashes.size === 1 && seedSets.size === 1 && !taskHashes.has(null);
  return (
    <>
      <PageHeader eyebrow="Models / held-out evaluation" title="Compare contenders without hiding what was not run." description="Base, memory, and fine-tuned checkpoints are comparable only when the task manifest and seed set are identical." actions={<StatusBadge tone={sample ? "warning" : "positive"}>{sample ? "Sample data" : "Live API"}</StatusBadge>} />
      <div className="mb-6 rounded-xl border border-white/9 bg-white/[0.02] p-4">
        <div className="flex items-start gap-3"><BrainCircuit className="mt-0.5 size-5 text-emerald-300" /><div><p className="text-sm font-semibold text-slate-200">Contender comparability</p><p className="mt-1 text-xs leading-5 text-slate-500">{evaluations.items.length < 2 ? "Not available — fewer than two evaluations were published." : comparable ? "Verified: contenders share the same task manifest and seed set." : "Not verified: task manifest or seed sets differ or are missing."}</p></div></div>
      </div>

      <section className="space-y-5">
        {evaluations.items.length ? evaluations.items.map((evaluation) => <EvaluationCard key={evaluation.id} evaluation={evaluation} />) : <Panel><EmptyState title="Evaluations not run" message="No held-out evaluation documents are published. Zeroes are not displayed because no denominators exist." /></Panel>}
      </section>

      <Panel className="mt-6">
        <PanelHeader eyebrow="Registry" title="Model checkpoints" action={<span className="text-xs text-slate-600">{checkpoints.total} published</span>} />
        {checkpoints.items.length ? <PanelBody className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{checkpoints.items.map((checkpoint) => <article key={checkpoint.id} className="rounded-xl border border-white/8 p-4"><div className="flex items-center justify-between gap-2"><p className="font-mono text-xs text-slate-200">{checkpoint.id}</p><StatusBadge tone="info">{stringAt(checkpoint.data, "status") ?? "registered"}</StatusBadge></div><dl className="mt-4 space-y-3 text-xs"><div><dt className="text-slate-600">Base model</dt><dd className="mt-1">{stringAt(checkpoint.data, "base_model") ?? "Not published"}</dd></div><div><dt className="text-slate-600">Training manifest</dt><dd className="mt-1 font-mono">{shortHash(stringAt(checkpoint.data, "manifest_hash"))}</dd></div><div><dt className="text-slate-600">Catalog</dt><dd className="mt-1 font-mono">{shortHash(stringAt(checkpoint.data, "catalog_hash"))}</dd></div></dl></article>)}</PanelBody> : <EmptyState title="No checkpoints registered" message="The training pipeline has not published a checkpoint document. This does not imply a failed model." />}
      </Panel>
    </>
  );
}
