"use client";

import { ArrowRight, Bot, CircleSlash2, FlaskConical, Sparkles } from "lucide-react";
import { useMemo, useState } from "react";
import { CrucibleApi, ApiError } from "@/lib/api/client";
import type { BuyerEvent, BuyerEventOf, BuyerRun } from "@/lib/api/types";
import { publicEnv } from "@/lib/env";
import { ErrorState } from "@/components/ui/data-state";
import { PageHeader } from "@/components/ui/page-header";
import { Panel, PanelBody, PanelHeader } from "@/components/ui/panel";
import { StatusBadge } from "@/components/ui/status-badge";
import { CheckoutFlow } from "./checkout-flow";
import { IntentPanel } from "./intent-panel";
import { ProductCard } from "./product-card";
import { ResearchTimeline } from "./research-timeline";

function first<T extends BuyerEvent["type"]>(events: BuyerEvent[], type: T) {
  return events.find((event): event is Extract<BuyerEvent, { type: T }> => event.type === type);
}

function all<T extends BuyerEvent["type"]>(events: BuyerEvent[], type: T) {
  return events.filter((event): event is Extract<BuyerEvent, { type: T }> => event.type === type);
}

function mergeRun(previous: BuyerRun, delta: BuyerRun): BuyerRun {
  const events = new Map(previous.events.map((event) => [event.seq, event]));
  for (const event of delta.events) events.set(event.seq, event);
  return { ...delta, events: [...events.values()].sort((a, b) => a.seq - b.seq) };
}

export function AgentWorkspace({
  sampleRun,
  sampleNoMatch,
}: {
  sampleRun?: BuyerRun | null;
  sampleNoMatch?: BuyerRun | null;
}) {
  const api = useMemo(
    () => new CrucibleApi(publicEnv.NEXT_PUBLIC_API_BASE_URL, publicEnv.NEXT_PUBLIC_DATA_MODE),
    [],
  );
  const sampleMode = publicEnv.NEXT_PUBLIC_DATA_MODE === "sample";
  const [request, setRequest] = useState("");
  const [budget, setBudget] = useState("");
  const [result, setResult] = useState<BuyerRun | null>(sampleRun ?? null);
  const [selectedProductId, setSelectedProductId] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  async function run() {
    if (!request.trim()) return;
    setRunning(true);
    setError(null);
    setSelectedProductId(null);
    try {
      let current = await api.startBuyerRun(
        request.trim(),
        budget || undefined,
        crypto.randomUUID(),
      );
      setResult(current);
      for (let attempt = 0; attempt < 20 && current.status === "running"; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 750));
        const delta = await api.pollBuyerRun(current.run_id, current.next_seq - 1);
        current = mergeRun(current, delta);
        setResult(current);
      }
      if (current.status === "running")
        throw new ApiError("timeout", "The run is still processing. Try again shortly.", 408);
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

  const events = result?.events ?? [];
  const intent = first(events, "intent_parsed");
  const assumptions = first(events, "assumptions");
  const research = all(events, "research");
  const products = all(events, "product_card");
  const reviews = all(events, "review_citation");
  const comparison = first(events, "comparison");
  const noMatch = first(events, "no_match");
  const quote = first(events, "quote");
  const confirmation = first(events, "confirmation_request");
  const approval = first(events, "paypal_approval");
  const receipt = first(events, "receipt");
  const runError = all(events, "error").at(-1);

  return (
    <>
      <PageHeader
        eyebrow="Buyer agent / grounded research"
        title="One request. An auditable decision."
        description="Describe the whole shopping problem in your own words. Crucible separates evidence, recommendation, quote, and purchase into explicit stages."
        actions={
          <StatusBadge tone={sampleMode ? "warning" : "positive"} dot>
            {sampleMode ? "Sample data" : "Live API"}
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
              <div className="mt-4 grid gap-3 sm:grid-cols-[12rem_1fr] sm:items-end">
                <label className="text-xs text-slate-500" htmlFor="budget-cap">
                  Explicit budget cap (optional)
                  <input
                    id="budget-cap"
                    type="number"
                    min="0.01"
                    step="0.01"
                    inputMode="decimal"
                    value={budget}
                    onChange={(event) => setBudget(event.target.value)}
                    placeholder="120.00"
                    className="mt-2 w-full rounded-lg border border-white/10 bg-[#0b1514] px-3 py-2 text-sm text-slate-200"
                  />
                </label>
                <button
                  type="button"
                  onClick={() => void run()}
                  disabled={!request.trim() || running}
                  className="inline-flex min-h-11 items-center justify-center gap-2 rounded-xl bg-emerald-200 px-5 py-3 text-sm font-semibold text-slate-950 hover:bg-emerald-100 disabled:bg-slate-700 disabled:text-slate-400"
                >
                  {running ? (
                    <FlaskConical className="size-4 animate-pulse" />
                  ) : (
                    <Sparkles className="size-4" />
                  )}
                  {running ? "Researching…" : "Run grounded research"}
                  {!running ? <ArrowRight className="size-4" /> : null}
                </button>
              </div>
            </div>
            {sampleMode ? (
              <div className="border-t border-amber-800/30 bg-amber-950/20 px-5 py-3 text-xs leading-5 text-amber-100/70 sm:px-7">
                <strong className="text-amber-200">Sample data.</strong> These are sanitized,
                synthetic-contract replays—not live model output or payment activity.
                <div className="mt-2 flex gap-2">
                  <button
                    type="button"
                    onClick={() => {
                      setResult(sampleRun ?? null);
                      setSelectedProductId(null);
                    }}
                    className="rounded border border-amber-700/40 px-2 py-1"
                  >
                    Recommendation replay
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setResult(sampleNoMatch ?? null);
                      setSelectedProductId(null);
                    }}
                    className="rounded border border-amber-700/40 px-2 py-1"
                  >
                    No-match replay
                  </button>
                </div>
              </div>
            ) : null}
          </Panel>

          {error ? (
            <ErrorState
              title={
                error.code === "model_unavailable" ? "Model runner unavailable" : "Agent run failed"
              }
              message={
                error.code === "model_unavailable"
                  ? "The operational API is healthy, but no model endpoint or checkpoint is configured. No output was simulated."
                  : error.message
              }
            />
          ) : null}
          {runError ? (
            <ErrorState title={runError.code.replaceAll("_", " ")} message={runError.message} />
          ) : null}
          {running ? (
            <Panel className="p-7" aria-live="polite">
              <div className="flex items-center gap-4">
                <span className="grid size-11 place-items-center rounded-full border border-emerald-700/50 bg-emerald-950">
                  <Bot className="size-5 animate-pulse text-emerald-300" />
                </span>
                <div>
                  <p className="font-semibold text-slate-100">Research in progress</p>
                  <p className="mt-1 text-sm text-slate-500">
                    Catalog evidence will appear only after validation.
                  </p>
                </div>
              </div>
            </Panel>
          ) : null}

          {result ? (
            <div className="space-y-6">
              <div className="flex flex-wrap gap-2">
                <StatusBadge
                  tone={
                    result.status === "failed"
                      ? "danger"
                      : result.status === "awaiting_confirmation"
                        ? "warning"
                        : "positive"
                  }
                >
                  {result.status.replaceAll("_", " ")}
                </StatusBadge>
                <StatusBadge tone="info">
                  {result.model ?? "Model identity unavailable"}
                </StatusBadge>
                <span className="self-center font-mono text-[0.65rem] text-slate-600">
                  run {result.run_id} · {result.latency_ms} ms · {result.tokens} tokens ·{" "}
                  {result.cost_known ? `${result.cost_usd ?? 0} USD` : "cost unknown"}
                </span>
              </div>
              {noMatch ? (
                <Panel className="overflow-hidden border-amber-800/45">
                  <div className="p-6 sm:p-8">
                    <CircleSlash2 className="size-8 text-amber-300" />
                    <p className="mt-4 font-mono text-[0.68rem] tracking-[0.16em] text-amber-300 uppercase">
                      Honest no-match
                    </p>
                    <h2 className="mt-2 text-2xl font-semibold tracking-[-0.03em] text-white">
                      No realistic match found.
                    </h2>
                    <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-300">
                      {noMatch.reason}
                    </p>
                    <p className="mt-2 text-sm leading-6 text-amber-100/70">
                      {noMatch.why_it_misses}
                    </p>
                    <dl className="mt-5 grid gap-3 text-xs sm:grid-cols-2">
                      <div className="rounded-lg border border-white/8 p-3">
                        <dt className="text-slate-600">Closest product ID</dt>
                        <dd className="mt-1 font-mono text-slate-300">
                          {noMatch.closest_product_id ?? "No closest product returned"}
                        </dd>
                      </div>
                      <div className="rounded-lg border border-white/8 p-3">
                        <dt className="text-slate-600">Closest-product verification</dt>
                        <dd className="mt-1 text-amber-200">
                          {noMatch.closest_verified
                            ? "Verified in catalog"
                            : "Not verified / unavailable"}
                        </dd>
                      </div>
                    </dl>
                  </div>
                </Panel>
              ) : (
                <Panel>
                  <PanelHeader
                    eyebrow="Grounded candidates"
                    title={`${products.length} researched product${products.length === 1 ? "" : "s"}`}
                    action={<StatusBadge tone="info">{reviews.length} cited reviews</StatusBadge>}
                  />
                  <PanelBody className="space-y-4">
                    {products.length ? (
                      products
                        .slice(0, 3)
                        .map((product) => (
                          <ProductCard
                            key={product.product_id}
                            product={product}
                            reviews={reviews.filter(
                              (review) => review.product_id === product.product_id,
                            )}
                            comparison={comparison}
                            unknownConstraints={assumptions?.unknown_constraints ?? []}
                            selected={selectedProductId === product.product_id}
                            selectable={quote?.product_id === product.product_id}
                            onSelect={() => setSelectedProductId(product.product_id)}
                          />
                        ))
                    ) : (
                      <p className="text-sm text-slate-500">
                        No validated product cards were returned.
                      </p>
                    )}
                  </PanelBody>
                </Panel>
              )}
              {!noMatch ? (
                <Panel>
                  <PanelHeader
                    eyebrow="Purchase boundary"
                    title="Quote and explicit confirmation"
                  />
                  <PanelBody>
                    <CheckoutFlow
                      runId={result.run_id}
                      selectedProductId={selectedProductId}
                      quote={quote}
                      confirmation={confirmation}
                      approval={approval}
                      receipt={receipt}
                      sampleMode={sampleMode}
                      onConfirm={(runId, pendingOrderId) =>
                        api.confirmBuyerRun(runId, pendingOrderId, true)
                      }
                      onRunUpdate={setResult}
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
              {intent ? (
                <IntentPanel
                  intent={{
                    category: intent.category,
                    max_total: intent.max_total,
                    currency: intent.currency,
                    budget_source: intent.budget_source,
                  }}
                  assumptions={assumptions?.assumptions ?? []}
                  unknownConstraints={assumptions?.unknown_constraints ?? []}
                />
              ) : (
                <p className="text-sm leading-6 text-slate-500">
                  Parsed constraints and explicit assumptions will appear here after a validated
                  run.
                </p>
              )}
            </PanelBody>
          </Panel>
          <Panel>
            <PanelHeader eyebrow="Audit trail" title="Research timeline" />
            <PanelBody>
              {research.length ? (
                <ResearchTimeline steps={research as BuyerEventOf<"research">[]} />
              ) : (
                <p className="text-sm leading-6 text-slate-500">
                  Search, product detail, review, comparison, and decision actions will be replayed
                  in order.
                </p>
              )}
            </PanelBody>
          </Panel>
        </aside>
      </div>
    </>
  );
}
