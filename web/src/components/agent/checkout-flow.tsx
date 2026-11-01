"use client";

import { ExternalLink, LockKeyhole, ShieldAlert, ShieldCheck, X } from "lucide-react";
import { useRef, useState } from "react";
import type { ConfirmResult, ProductPick, ProposeResult } from "@/lib/api/types";
import { ApiError } from "@/lib/api/client";
import { StatusBadge } from "@/components/ui/status-badge";

export type PurchaseContext = {
  taskId: string;
  agentId: string;
  budgetCap: string;
  variant: string;
};

export function checkoutErrorMessage(cause: unknown): string {
  if (!(cause instanceof ApiError)) return "The sandbox payment request could not be completed.";
  const messages: Record<string, string> = {
    quote_stale: "The verified quote expired. Request a fresh quote before confirming.",
    quote_changed: "The price or all-in total changed. Review the new quote before confirming.",
    price_mismatch: "The current catalog price no longer matches the recommendation.",
    budget_exceeded: "The verified total exceeds the shopper's budget cap. No order was created.",
    out_of_stock: "The selected product or variant is no longer available.",
    confirmation_required: "Explicit confirmation is required before sandbox capture.",
    payment_failed: "PayPal sandbox capture failed. No completed receipt was returned.",
  };
  return messages[cause.code] ?? cause.message;
}

export function CheckoutFlow({
  pick,
  purchaseContext,
  onPropose,
  onConfirm,
}: {
  pick: ProductPick | null;
  purchaseContext: PurchaseContext | null;
  onPropose: (pick: ProductPick, context: PurchaseContext) => Promise<ProposeResult>;
  onConfirm: (pendingOrderId: string) => Promise<ConfirmResult>;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [quote, setQuote] = useState<ProposeResult | null>(null);
  const [receipt, setReceipt] = useState<ConfirmResult | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function quoteSelected() {
    if (!pick || !purchaseContext) return;
    setBusy(true);
    setError(null);
    try {
      const result = await onPropose(pick, purchaseContext);
      setQuote(result);
      dialog.current?.showModal();
    } catch (cause) {
      setError(checkoutErrorMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  async function capture() {
    if (!quote || !confirmed) return;
    setBusy(true);
    setError(null);
    try {
      const result = await onConfirm(quote.pending_order_id);
      setReceipt(result);
      dialog.current?.close();
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
        <h3 className="mt-3 font-semibold text-emerald-100">Sandbox capture completed</h3>
        <dl className="mt-3 grid gap-2 text-xs text-emerald-100/70 sm:grid-cols-2">
          <div><dt>Order</dt><dd className="font-mono">{receipt.order_id}</dd></div>
          <div><dt>Capture</dt><dd className="font-mono">{receipt.capture_id}</dd></div>
          <div><dt>Amount</dt><dd>{receipt.amount} {receipt.currency}</dd></div>
          <div><dt>Status</dt><dd>{receipt.status}</dd></div>
        </dl>
      </div>
    );
  }

  const enabled = Boolean(pick && purchaseContext);
  return (
    <div className="space-y-3">
      {!purchaseContext ? (
        <div className="rounded-xl border border-amber-800/50 bg-amber-950/20 p-4">
          <p className="flex items-center gap-2 text-sm font-semibold text-amber-200">
            <ShieldAlert className="size-4" aria-hidden="true" /> Checkout context unavailable
          </p>
          <p className="mt-2 text-xs leading-5 text-amber-100/65">
            Recommendation is not purchase authorization. The API did not return a task ID, agent ID,
            variant, and verified budget cap, so quote creation is disabled.
          </p>
        </div>
      ) : null}
      {error && !quote ? <p role="alert" className="text-sm text-rose-300">{error}</p> : null}
      <button
        type="button"
        disabled={!enabled || busy}
        onClick={() => void quoteSelected()}
        className="inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-xl bg-emerald-200 px-4 py-3 text-sm font-semibold text-slate-950 hover:bg-emerald-100 disabled:bg-slate-700 disabled:text-slate-400"
      >
        <LockKeyhole className="size-4" aria-hidden="true" />
        {busy ? "Verifying quote…" : pick ? "Verify all-in quote" : "Select a recommendation first"}
      </button>

      <dialog
        ref={dialog}
        onClose={() => setConfirmed(false)}
        className="m-auto w-[min(92vw,34rem)] rounded-2xl border border-white/15 bg-[#0b1514] p-0 text-slate-100 shadow-2xl backdrop:bg-black/75"
        aria-labelledby="confirm-title"
      >
        {quote ? (
          <div>
            <header className="flex items-start justify-between border-b border-white/10 p-5">
              <div>
                <StatusBadge tone="warning">Sandbox payment</StatusBadge>
                <h2 id="confirm-title" className="mt-3 text-xl font-semibold">Confirm purchase capture</h2>
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
              {error ? <p role="alert" className="rounded-lg border border-rose-800/50 bg-rose-950/30 p-3 text-sm text-rose-200">{error}</p> : null}
              <div className="rounded-xl border border-white/10 bg-black/20 p-4">
                <p className="text-xs text-slate-500">Verified total</p>
                <p className="mt-1 text-3xl font-semibold text-emerald-200 tabular-nums">
                  {quote.total} {quote.currency}
                </p>
                <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-500">
                  <span>Basis: {quote.quote_basis}</span>
                  <span>•</span>
                  <span>Quote ID: {quote.quote_id ?? "not provided"}</span>
                  <span>•</span>
                  <span>Expiry: not provided by API</span>
                </div>
              </div>
              {quote.approval_url ? (
                <a
                  href={quote.approval_url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-2 text-sm text-cyan-300 underline underline-offset-4"
                >
                  Open PayPal sandbox approval <ExternalLink className="size-3.5" />
                </a>
              ) : (
                <p className="text-xs leading-5 text-slate-500">No external approval URL was returned.</p>
              )}
              <label className="flex items-start gap-3 rounded-xl border border-white/10 p-4 text-sm leading-5 text-slate-300">
                <input
                  type="checkbox"
                  checked={confirmed}
                  onChange={(event) => setConfirmed(event.target.checked)}
                  className="mt-0.5 size-4 accent-emerald-300"
                />
                I explicitly authorize this sandbox capture for the verified total shown above.
              </label>
              <button
                type="button"
                disabled={!confirmed || busy}
                onClick={() => void capture()}
                className="w-full rounded-xl bg-emerald-200 px-4 py-3 text-sm font-semibold text-slate-950 disabled:bg-slate-700 disabled:text-slate-400"
              >
                {busy ? "Capturing…" : "Confirm sandbox purchase"}
              </button>
            </div>
          </div>
        ) : null}
      </dialog>
    </div>
  );
}
