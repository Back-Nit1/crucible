"use client";

import { ArrowRight, Bot, CircleSlash2, FlaskConical, Sparkles } from "lucide-react";
import { useMemo, useState } from "react";
import { CrucibleApi, ApiError } from "@/lib/api/client";
import type { AgentRunResult, ProductPick } from "@/lib/api/types";
import { publicEnv } from "@/lib/env";
import { ErrorState } from "@/components/ui/data-state";
import { PageHeader } from "@/components/ui/page-header";
import { Panel, PanelBody, PanelHeader } from "@/components/ui/panel";
import { StatusBadge } from "@/components/ui/status-badge";
import { CheckoutFlow } from "./checkout-flow";
import { IntentPanel } from "./intent-panel";
import { ProductCard } from "./product-card";
import { ResearchTimeline } from "./research-timeline";

export function AgentWorkspace({ sampleNoMatch }: { sampleNoMatch?: AgentRunResult | null }) {
  const api = useMemo(
    () => new CrucibleApi(publicEnv.NEXT_PUBLIC_API_BASE_URL, publicEnv.NEXT_PUBLIC_DATA_MODE),
    [],
  );
  const [request, setRequest] = useState("");
  const [mode, setMode] = useState<"trained" | "base">("trained");
  const [result, setResult] = useState<AgentRunResult | null>(sampleNoMatch ?? null);
  const [selected, setSelected] = useState<ProductPick | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  async function run() {
    if (!request.trim()) return;
    setRunning(true);
    setError(null);
    setSelected(null);
    try {
      setResult(await api.runAgent(request.trim(), mode));
    } catch (cause) {
      setResult(null);
      setError(
        cause instanceof ApiError
          ? cause
          : new ApiError("client_error", "The agent run could not be completed.", 0),
      );
    } finally {
      setRunning(false);
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="Buyer agent / grounded research"
        title="One request. An auditable decision."
        description="Describe the whole shopping problem in your own words. Crucible separates evidence, recommendation, quote, and purchase into explicit stages."
        actions={
          <StatusBadge tone={publicEnv.NEXT_PUBLIC_DATA_MODE === "sample" ? "warning" : "positive"} dot>
            {publicEnv.NEXT_PUBLIC_DATA_MODE === "sample" ? "Sample data" : "Live API"}
          </StatusBadge>
        }
      />

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.55fr)_minmax(19rem,0.75fr)]">
        <div className="space-y-6">
          <Panel className="overflow-hidden">
            <div className="border-b border-white/8 bg-gradient-to-br from-emerald-300/[0.06] to-transparent p-5 sm:p-7">
              <label htmlFor="shopping-request" className="text-sm font-semibold text-slate-100">
                What should the agent find?
              </label>
              <textarea
                id="shopping-request"
                value={request}
                onChange={(event) => setRequest(event.target.value)}
                rows={5}
                maxLength={4000}
                placeholder="I need comfortable over-ear headphones for long study sessions, under $120 all-in. I wear glasses, so pressure matters…"
                className="mt-3 w-full resize-y rounded-xl border border-white/12 bg-black/25 p-4 text-base leading-7 text-slate-100 placeholder:text-slate-600 focus:border-emerald-300/60"
              />
              <div className="mt-4 flex flex-col justify-between gap-3 sm:flex-row sm:items-center">
                <div className="flex items-center gap-3">
                  <label htmlFor="model-mode" className="font-mono text-[0.65rem] text-slate-500 uppercase">
                    Contender
                  </label>
                  <select
                    id="model-mode"
                    value={mode}
                    onChange={(event) => setMode(event.target.value as "trained" | "base")}
                    className="rounded-lg border border-white/10 bg-[#0b1514] px-3 py-2 text-xs text-slate-200"
                  >
                    <option value="trained">Fine-tuned + memory</option>
                    <option value="base">Base model</option>
                  </select>
                </div>
                <button
                  type="button"
                  onClick={() => void run()}
                  disabled={!request.trim() || running}
                  className="inline-flex min-h-11 items-center justify-center gap-2 rounded-xl bg-emerald-200 px-5 py-3 text-sm font-semibold text-slate-950 hover:bg-emerald-100 disabled:bg-slate-700 disabled:text-slate-400"
                >
                  {running ? <FlaskConical className="size-4 animate-pulse" /> : <Sparkles className="size-4" />}
                  {running ? "Researching…" : "Run grounded research"}
                  {!running ? <ArrowRight className="size-4" /> : null}
                </button>
              </div>
            </div>
            {publicEnv.NEXT_PUBLIC_DATA_MODE === "sample" ? (
              <div className="border-t border-amber-800/30 bg-amber-950/20 px-5 py-3 text-xs leading-5 text-amber-100/70 sm:px-7">
                <strong className="text-amber-200">Sample data.</strong> The replay below is a sanitized API
                sample. Submitting a new request is intentionally read-only and will not simulate a model.
              </div>
            ) : null}
          </Panel>

          {error ? (
            <ErrorState
              title={error.code === "model_unavailable" ? "Model runner unavailable" : "Agent run failed"}
              message={
                error.code === "model_unavailable"
                  ? "The operational API is healthy, but no model endpoint or checkpoint is configured. No output was simulated."
                  : error.message
              }
            />
          ) : null}

          {running ? (
            <Panel className="p-7" aria-live="polite">
              <div className="flex items-center gap-4">
                <span className="grid size-11 place-items-center rounded-full border border-emerald-700/50 bg-emerald-950">
                  <Bot className="size-5 animate-pulse text-emerald-300" />
                </span>
                <div>
                  <p className="font-semibold text-slate-100">Research in progress</p>
                  <p className="mt-1 text-sm text-slate-500">Catalog evidence will appear only after validation.</p>
                </div>
              </div>
            </Panel>
          ) : null}

          {result ? (
            <div className="space-y-6">
              {result.no_match ? (
                <Panel className="overflow-hidden border-amber-800/45">
                  <div className="p-6 sm:p-8">
                    <CircleSlash2 className="size-8 text-amber-300" aria-hidden="true" />
                    <p className="mt-4 font-mono text-[0.68rem] tracking-[0.16em] text-amber-300 uppercase">
                      Honest no-match
                    </p>
                    <h2 className="mt-2 text-2xl font-semibold tracking-[-0.03em] text-white">
                      No realistic match found.
                    </h2>
                    <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-300">{result.final_answer}</p>
                    <dl className="mt-5 grid gap-3 text-xs sm:grid-cols-2">
                      <div className="rounded-lg border border-white/8 p-3">
                        <dt className="text-slate-600">Closest product ID</dt>
                        <dd className="mt-1 font-mono text-slate-300">
                          {result.closest_product_id ?? "No closest product returned"}
                        </dd>
                      </div>
                      <div className="rounded-lg border border-white/8 p-3">
                        <dt className="text-slate-600">Outcome</dt>
                        <dd className="mt-1 text-amber-200">No purchase proposed</dd>
                      </div>
                    </dl>
                  </div>
                </Panel>
              ) : (
                <Panel>
                  <PanelHeader
                    eyebrow="Grounded candidates"
                    title={`${result.picks.length} recommendation${result.picks.length === 1 ? "" : "s"}`}
                    action={<StatusBadge tone="info">{result.model}</StatusBadge>}
                  />
                  <PanelBody className="space-y-4">
                    {result.picks.length ? (
                      result.picks.map((pick) => (
                        <ProductCard
                          key={pick.product_id}
                          pick={pick}
                          selected={selected?.product_id === pick.product_id}
                          onSelect={() => setSelected(pick)}
                        />
                      ))
                    ) : (
                      <p className="text-sm text-slate-500">No picks were returned.</p>
                    )}
                  </PanelBody>
                </Panel>
              )}

              {!result.no_match ? (
                <Panel>
                  <PanelHeader eyebrow="Purchase boundary" title="Quote and explicit confirmation" />
                  <PanelBody>
                    <CheckoutFlow
                      pick={selected}
                      purchaseContext={null}
                      onPropose={(pick, context) =>
                        api.propose({
                          task_id: context.taskId,
                          agent_id: context.agentId,
                          product_id: pick.product_id,
                          variant: context.variant,
                          expected_total: String(pick.price),
                          budget_cap: context.budgetCap,
                        })
                      }
                      onConfirm={(id) => api.confirm(id, true)}
                    />
                  </PanelBody>
                </Panel>
              ) : null}
            </div>
          ) : null}
        </div>

        <aside className="space-y-6">
          <Panel>
            <PanelHeader eyebrow="Interpretation" title="Intent & assumptions" />
            <PanelBody>
              {result ? (
                <IntentPanel intent={result.parsed_intent} assumptions={result.assumptions} />
              ) : (
                <p className="text-sm leading-6 text-slate-500">
                  Parsed constraints and explicit assumptions will appear here after a validated run.
                </p>
              )}
            </PanelBody>
          </Panel>
          <Panel>
            <PanelHeader eyebrow="Audit trail" title="Research timeline" />
            <PanelBody>
              {result?.steps.length ? (
                <ResearchTimeline steps={result.steps} />
              ) : (
                <p className="text-sm leading-6 text-slate-500">
                  Search, product detail, review, comparison, and decision actions will be replayed in order.
                </p>
              )}
            </PanelBody>
          </Panel>
        </aside>
      </div>
    </>
  );
}
