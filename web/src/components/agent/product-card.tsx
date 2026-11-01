import { BookOpen, CalendarClock, CircleAlert, Database, PackageSearch } from "lucide-react";
import type { ProductPick } from "@/lib/api/types";
import { StatusBadge } from "@/components/ui/status-badge";

function money(value: string | number, currency: string) {
  const numeric = Number(value);
  return Number.isFinite(numeric)
    ? new Intl.NumberFormat("en-US", { style: "currency", currency }).format(numeric)
    : `${value} ${currency}`;
}

export function ProductCard({
  pick,
  selected,
  onSelect,
}: {
  pick: ProductPick;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <article
      className={`rounded-2xl border p-5 transition-colors ${
        selected
          ? "border-emerald-400/55 bg-emerald-300/[0.055]"
          : "border-white/9 bg-white/[0.02] hover:border-white/16"
      }`}
    >
      <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-start">
        <div>
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <StatusBadge tone={pick.snapshot ? "info" : "positive"}>
              {pick.snapshot ? "Frozen snapshot" : "Live source"}
            </StatusBadge>
            <span className="font-mono text-[0.65rem] text-slate-600">{pick.product_id}</span>
          </div>
          <h3 className="text-lg font-semibold tracking-[-0.025em] text-white">{pick.title}</h3>
          <p className="mt-2 text-2xl font-semibold text-emerald-200 tabular-nums">
            {money(pick.price, pick.currency)}
          </p>
          <p className="mt-1 text-xs text-slate-600">Item price; all-in quote not yet verified</p>
        </div>
        <label className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-white/10 px-3 py-2 text-xs font-semibold text-slate-200">
          <input
            type="radio"
            name="recommendation"
            checked={selected}
            onChange={onSelect}
            className="accent-emerald-300"
          />
          Select for quote
        </label>
      </div>

      <div className="mt-5 grid gap-3 text-xs sm:grid-cols-3">
        <div className="rounded-lg border border-white/7 bg-black/15 p-3">
          <Database className="mb-2 size-3.5 text-cyan-300" aria-hidden="true" />
          <p className="text-slate-600">Source</p>
          <p className="mt-1 break-words text-slate-300">{pick.source}</p>
        </div>
        <div className="rounded-lg border border-white/7 bg-black/15 p-3">
          <CalendarClock className="mb-2 size-3.5 text-cyan-300" aria-hidden="true" />
          <p className="text-slate-600">As of</p>
          <p className="mt-1 text-slate-300">{new Date(pick.as_of).toLocaleDateString()}</p>
        </div>
        <div className="rounded-lg border border-white/7 bg-black/15 p-3">
          <PackageSearch className="mb-2 size-3.5 text-amber-300" aria-hidden="true" />
          <p className="text-slate-600">Category / stock / size</p>
          <p className="mt-1 text-amber-100/80">Not provided — unknown</p>
        </div>
      </div>

      <div className="mt-5 grid gap-4 lg:grid-cols-2">
        <div>
          <p className="font-mono text-[0.64rem] tracking-[0.1em] text-slate-600 uppercase">Why it matches</p>
          <p className="mt-2 text-sm leading-6 text-slate-300">{pick.reason}</p>
        </div>
        <div>
          <p className="flex items-center gap-2 font-mono text-[0.64rem] tracking-[0.1em] text-slate-600 uppercase">
            <CircleAlert className="size-3" aria-hidden="true" /> Why it might not
          </p>
          <p className="mt-2 text-sm leading-6 text-amber-100/65">
            Stock, requested variant, and all-in total are not present in this recommendation contract.
          </p>
        </div>
      </div>

      <details className="mt-5 border-t border-white/8 pt-4">
        <summary className="flex list-none items-center gap-2 text-xs font-semibold text-slate-300 [&::-webkit-details-marker]:hidden">
          <BookOpen className="size-3.5 text-emerald-300" aria-hidden="true" /> Review evidence (
          {pick.review_evidence.length})
        </summary>
        {pick.review_evidence.length ? (
          <div className="mt-3 space-y-3">
            {pick.review_evidence.map((evidence) => (
              <blockquote
                key={`${evidence.claim}-${evidence.review_ids.join("-")}`}
                className="rounded-xl border border-white/8 bg-black/15 p-4"
              >
                <p className="text-sm leading-6 text-slate-300">{evidence.claim}</p>
                {evidence.excerpt ? (
                  <p className="mt-2 border-l border-emerald-300/30 pl-3 text-xs leading-5 text-slate-500">
                    “{evidence.excerpt}”
                  </p>
                ) : null}
                <footer className="mt-3 flex flex-wrap gap-2">
                  {evidence.review_ids.map((id) => (
                    <span key={id} className="break-all font-mono text-[0.6rem] text-cyan-300/70">
                      {id}
                    </span>
                  ))}
                  {evidence.rating !== null && evidence.rating !== undefined ? (
                    <span className="text-[0.65rem] text-slate-500">{evidence.rating}/5 rating</span>
                  ) : null}
                </footer>
              </blockquote>
            ))}
          </div>
        ) : (
          <p className="mt-3 text-xs leading-5 text-slate-500">
            No grounded review claims were returned. Ratings are not used as a substitute.
          </p>
        )}
      </details>
    </article>
  );
}
