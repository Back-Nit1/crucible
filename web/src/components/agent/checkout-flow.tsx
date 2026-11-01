"use client";

import { ExternalLink, LockKeyhole, ShieldAlert, ShieldCheck, X } from "lucide-react";
import { useRef, useState } from "react";
import type { BuyerEventOf, BuyerRun } from "@/lib/api/types";
import { ApiError } from "@/lib/api/client";
import { StatusBadge } from "@/components/ui/status-badge";

export function checkoutErrorMessage(cause: unknown): string {
  if (!(cause instanceof ApiError)) return "The payment request could not be completed.";
  const messages: Record<string, string> = {
    quote_stale: "The verified quote expired. Request a fresh quote before confirming.",
    quote_changed: "The price or all-in total changed. Review a new quote before confirming.",
    price_mismatch: "The current catalog price no longer matches the recommendation.",
    budget_exceeded: "The verified total exceeds the shopper's budget cap. No order was created.",
    out_of_stock: "The selected product or variant is no longer available.",
    confirmation_required: "Explicit confirmation is required before capture.",
    payment_not_approved: "Approve the sandbox order in PayPal, then confirm again.",
    payment_failed: "The payment backend rejected capture. No completed receipt was returned.",
  };
  return messages[cause.code] ?? cause.message;
}

function amount(value: string | number, currency: string) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency }).format(Number(value));
}

export function CheckoutFlow({
  runId,
  selectedProductId,
  quote,
  confirmation,
  approval,
  receipt,
  sampleMode,
  onConfirm,
  onRunUpdate,
}: {
  runId: string;
  selectedProductId: string | null;
  quote?: BuyerEventOf<"quote">;
  confirmation?: BuyerEventOf<"confirmation_request">;
  approval?: BuyerEventOf<"paypal_approval">;
  receipt?: BuyerEventOf<"receipt">;
  sampleMode: boolean;
  onConfirm: (runId: string, pendingOrderId: string) => Promise<BuyerRun>;
  onRunUpdate: (run: BuyerRun) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function capture() {
    if (!confirmation || !confirmed) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await onConfirm(runId, confirmation.pending_order_id);
      onRunUpdate(updated);
      if (updated.events.some((event) => event.type === "receipt")) dialog.current?.close();
    } catch (cause) {
      setError(checkoutErrorMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  if (receipt) {
    return (
      <div className="rounded-xl border border-emerald-700/50 bg-emerald-950/30 p-5" role="status">
        <ShieldCheck className="size-6 text-emerald-300" aria-hidden="true" />
        <h3 className="mt-3 font-semibold text-emerald-100">
          {sampleMode
            ? "Sample receipt replayed"
            : `${receipt.mode === "mock" ? "Mock" : "Sandbox"} capture completed`}
        </h3>
        {sampleMode ? (
          <p className="mt-2 text-xs text-amber-200">Sample data only. No payment was attempted.</p>
        ) : null}
        <dl className="mt-3 grid gap-2 text-xs text-emerald-100/70 sm:grid-cols-2">
          <div>
            <dt>Order</dt>
            <dd className="break-all font-mono">{receipt.order_id}</dd>
          </div>
          <div>
            <dt>Capture</dt>
            <dd className="break-all font-mono">{receipt.capture_id}</dd>
          </div>
          <div>
            <dt>Amount</dt>
            <dd>{amount(receipt.amount, receipt.currency)}</dd>
          </div>
          <div>
            <dt>Status</dt>
            <dd>{receipt.status}</dd>
          </div>
        </dl>
      </div>
    );
  }

  const selectedQuote = Boolean(quote && selectedProductId === quote.product_id);
  const enabled = Boolean(selectedQuote && confirmation && quote?.fresh && quote.within_budget);
  const mode = approval?.mode ?? "mock";

  return (
    <div className="space-y-3">
      {!quote || !confirmation ? (
        <div className="rounded-xl border border-amber-800/50 bg-amber-950/20 p-4">
          <p className="flex items-center gap-2 text-sm font-semibold text-amber-200">
            <ShieldAlert className="size-4" aria-hidden="true" /> Verified quote unavailable
          </p>
          <p className="mt-2 text-xs leading-5 text-amber-100/65">
            Recommendation is not purchase authorization. The API did not return a quote and pending
            confirmation request, so checkout is disabled.
          </p>
        </div>
      ) : null}
      {quote && (!quote.fresh || !quote.within_budget) ? (
        <p
          role="alert"
          className="rounded-lg border border-rose-800/50 bg-rose-950/30 p-3 text-sm text-rose-200"
        >
          {!quote.fresh ? "This quote is expired." : "This quote exceeds the verified budget."} No
          capture can be requested.
        </p>
      ) : null}
      <button
        type="button"
        disabled={!enabled || busy}
        onClick={() => dialog.current?.showModal()}
        className="inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-xl bg-emerald-200 px-4 py-3 text-sm font-semibold text-slate-950 hover:bg-emerald-100 disabled:bg-slate-700 disabled:text-slate-400"
      >
        <LockKeyhole className="size-4" aria-hidden="true" />
        {!selectedProductId
          ? "Select the quoted recommendation first"
          : selectedQuote
            ? "Review verified quote"
            : "Selected product has no checkout quote"}
      </button>

      <dialog
        ref={dialog}
        onClose={() => setConfirmed(false)}
        className="m-auto w-[min(92vw,36rem)] rounded-2xl border border-white/15 bg-[#0b1514] p-0 text-slate-100 shadow-2xl backdrop:bg-black/75"
        aria-labelledby="confirm-title"
      >
        {quote && confirmation ? (
          <div>
            <header className="flex items-start justify-between border-b border-white/10 p-5">
              <div>
                <StatusBadge tone="warning">
                  {sampleMode ? "Sample replay" : `${mode} payment`}
                </StatusBadge>
                <h2 id="confirm-title" className="mt-3 text-xl font-semibold">
                  Recommendation is not a purchase
                </h2>
                <p className="mt-1 text-xs text-slate-500">
                  Review the API-verified total, then authorize capture separately.
                </p>
              </div>
              <button
                type="button"
                onClick={() => dialog.current?.close()}
                className="grid size-9 place-items-center rounded-lg border border-white/10 text-slate-400"
                aria-label="Close confirmation"
              >
                <X className="size-4" />
              </button>
            </header>
            <div className="space-y-5 p-5">
              {error ? (
                <p
                  role="alert"
                  className="rounded-lg border border-rose-800/50 bg-rose-950/30 p-3 text-sm text-rose-200"
                >
                  {error}
                </p>
              ) : null}
              <div className="rounded-xl border border-white/10 bg-black/20 p-4">
                <p className="text-xs text-slate-500">Verified total</p>
                <p className="mt-1 text-3xl font-semibold text-emerald-200 tabular-nums">
                  {amount(quote.total, quote.currency)}
                </p>
                <dl className="mt-4 grid grid-cols-2 gap-2 text-xs text-slate-400">
                  <dt>Subtotal</dt>
                  <dd className="text-right">{amount(quote.subtotal, quote.currency)}</dd>
                  <dt>Shipping</dt>
                  <dd className="text-right">
                    {quote.shipping === null ? "Unknown" : amount(quote.shipping, quote.currency)}
                  </dd>
                  <dt>Tax</dt>
                  <dd className="text-right">
                    {quote.tax === null ? "Unknown" : amount(quote.tax, quote.currency)}
                  </dd>
                  <dt>Discounts</dt>
                  <dd className="text-right">{amount(quote.discounts, quote.currency)}</dd>
                </dl>
                <div className="mt-3 space-y-1 text-xs text-slate-500">
                  <p>Basis: {quote.basis.replaceAll("_", " ")}</p>
                  <p>Budget checked on: {quote.budget_checked_on.replaceAll("_", " ")}</p>
                  <p>Fresh until: {new Date(quote.expires_at).toLocaleString()}</p>
                  <p className="break-all font-mono">Quote {quote.quote_id}</p>
                </div>
                {quote.unknown_components.length ? (
                  <p className="mt-3 text-xs text-amber-200">
                    Not included: {quote.unknown_components.join(", ")}
                  </p>
                ) : null}
              </div>
              {approval?.mode === "sandbox" && approval.approval_url ? (
                <a
                  href={approval.approval_url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-2 text-sm text-cyan-300 underline underline-offset-4"
                >
                  Open PayPal sandbox approval <ExternalLink className="size-3.5" />
                </a>
              ) : (
                <p className="text-xs leading-5 text-slate-500">
                  Payment backend: {mode.toUpperCase()} · status:{" "}
                  {approval?.status ?? "not returned"}
                </p>
              )}
              <p className="text-sm leading-6 text-slate-300">{confirmation.summary}</p>
              <label className="flex items-start gap-3 rounded-xl border border-white/10 p-4 text-sm leading-5 text-slate-300">
                <input
                  type="checkbox"
                  checked={confirmed}
                  onChange={(event) => setConfirmed(event.target.checked)}
                  className="mt-0.5 size-4 accent-emerald-300"
                />
                {sampleMode
                  ? "I understand this replays a sanitized sample and does not make a purchase."
                  : `I explicitly authorize this ${mode} capture for the verified total shown above.`}
              </label>
              <button
                type="button"
                disabled={!confirmed || busy}
                onClick={() => void capture()}
                className="w-full rounded-xl bg-emerald-200 px-4 py-3 text-sm font-semibold text-slate-950 disabled:bg-slate-700 disabled:text-slate-400"
              >
                {busy
                  ? "Confirming…"
                  : sampleMode
                    ? "Replay sample receipt"
                    : `Confirm ${mode} purchase`}
              </button>
            </div>
          </div>
        ) : null}
      </dialog>
    </div>
  );
}
