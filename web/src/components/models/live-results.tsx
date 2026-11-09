"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Panel, PanelBody, PanelHeader } from "@/components/ui/panel";
import { StatusBadge } from "@/components/ui/status-badge";

type Rate = { value: number | null; numerator: number | null; denominator: number | null };
export type Probe = {
  id: string;
  status: string | null;
  finished_at: string | null;
  checkpoint: string | null;
  model: string | null;
  rates: Record<string, Rate>;
  failed_thresholds: string[];
  cost_usd: string | null;
  latency_p50_ms: number | null;
};
export type EvaluationProgress = {
  evaluation_id: string;
  status: "running" | "complete" | "reported";
  contenders: {
    contender: string;
    kind: string | null;
    done: number;
    expected: number;
    killed: number;
    cost_usd: string;
  }[];
};
export type LiveModels = { probes: Probe[]; evaluations: EvaluationProgress[] };

const RATES = [
  ["valid_structured_call", "Valid tool call"],
  ["schema_valid_arguments", "Schema-valid args"],
  ["parse_intent_first", "Parses intent first"],
  ["malformed", "Malformed"],
] as const;

const REFRESH_MS = 30_000;

/** Re-renders the server page every 30 s so new probe files, evaluation episodes and published reports appear without a reload. */
export function AutoRefresh() {
  const router = useRouter();
  const [at, setAt] = useState<Date | null>(null); // set on the client only: no server/client time mismatch
  useEffect(() => {
    const id = setInterval(() => {
      if (document.visibilityState === "visible") {
        router.refresh();
        setAt(new Date());
      }
    }, REFRESH_MS);
    return () => clearInterval(id);
  }, [router]);
  return (
    <span className="text-xs text-slate-600">
      Auto-refresh 30 s{at ? ` · checked ${at.toLocaleTimeString()}` : ""}
    </span>
  );
}

const pct = (r?: Rate) => (r?.value == null ? "Not measured" : `${(r.value * 100).toFixed(0)}%`);

export function LiveResults({ live }: { live: LiveModels | null }) {
  if (!live) return null;
  return (
    <Panel className="mb-6">
      <PanelHeader eyebrow="As results land" title="Live model results" action={<AutoRefresh />} />
      <PanelBody className="space-y-5">
        {live.evaluations.map((ev) => (
          <div key={ev.evaluation_id}>
            <div className="mb-2 flex items-center gap-2">
              <p className="font-mono text-xs text-slate-300">{ev.evaluation_id}</p>
              <StatusBadge tone={ev.status === "running" ? "info" : "positive"}>
                {ev.status}
              </StatusBadge>
            </div>
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {ev.contenders.map((c) => (
                <article key={c.contender} className="rounded-xl border border-white/8 p-3">
                  <p className="font-mono text-xs text-slate-200">{c.contender}</p>
                  <div className="mt-2 h-1.5 rounded-full bg-white/5">
                    <div
                      className="h-full rounded-full bg-emerald-400/70"
                      style={{
                        width: `${c.expected ? Math.min(100, (c.done / c.expected) * 100) : 0}%`,
                      }}
                    />
                  </div>
                  <p className="mt-2 text-xs text-slate-500">
                    {c.done} / {c.expected} episodes · {c.killed} killed · ${c.cost_usd}
                  </p>
                </article>
              ))}
            </div>
          </div>
        ))}
        {live.probes.map((p) => (
          <article key={p.id} className="rounded-xl border border-white/8 p-3">
            <div className="flex flex-wrap items-center gap-2">
              <p className="text-sm text-slate-200">
                Tool-call probe · {p.checkpoint ?? "unknown checkpoint"}
              </p>
              <StatusBadge
                tone={
                  p.status === "passed" ? "positive" : p.status === "failed" ? "danger" : "neutral"
                }
              >
                {p.status ?? "unknown"}
              </StatusBadge>
              <span className="text-xs text-slate-600">
                {p.model} ·{" "}
                {p.finished_at
                  ? `${p.finished_at.slice(0, 16).replace("T", " ")} UTC`
                  : "not finished"}
              </span>
            </div>
            {p.status === "passed" || p.status === "failed" ? (
              <div className="mt-3 grid gap-3 sm:grid-cols-3 xl:grid-cols-6">
                {RATES.map(([key, label]) => (
                  <div key={key}>
                    <p className="text-xs text-slate-600">{label}</p>
                    <p className="mt-1 text-sm tabular-nums">{pct(p.rates[key])}</p>
                    <p className="text-[0.65rem] text-slate-600">
                      {p.rates[key]
                        ? `${p.rates[key].numerator} / ${p.rates[key].denominator}`
                        : ""}
                    </p>
                  </div>
                ))}
                <div>
                  <p className="text-xs text-slate-600">p50 latency</p>
                  <p className="mt-1 text-sm">
                    {p.latency_p50_ms == null
                      ? "Not measured"
                      : `${Math.round(p.latency_p50_ms)} ms`}
                  </p>
                </div>
                <div>
                  <p className="text-xs text-slate-600">Cost</p>
                  <p className="mt-1 text-sm">
                    {p.cost_usd == null ? "Unknown" : `$${p.cost_usd}`}
                  </p>
                </div>
              </div>
            ) : (
              <p className="mt-2 text-xs text-slate-500">Not run: no numbers recorded.</p>
            )}
          </article>
        ))}
        {!live.probes.length && !live.evaluations.length && (
          <p className="text-xs text-slate-500">
            Nothing recorded yet. Probe files and evaluation episodes appear here as they are
            written.
          </p>
        )}
      </PanelBody>
    </Panel>
  );
}
