import { BookOpen, CalendarClock, CircleAlert, Database, PackageSearch } from "lucide-react";
import type { BuyerEventOf } from "@/lib/api/types";
import { StatusBadge } from "@/components/ui/status-badge";

function money(value: string | number, currency: string) {
  const numeric = Number(value);
  return Number.isFinite(numeric)
    ? new Intl.NumberFormat("en-US", { style: "currency", currency }).format(numeric)
    : `${value} ${currency}`;
}

export function ProductCard({
  product,
  reviews,
  comparison,
  unknownConstraints,
  selected,
  selectable,
  onSelect,
}: {
  product: BuyerEventOf<"product_card">;
  reviews: BuyerEventOf<"review_citation">[];
  comparison?: BuyerEventOf<"comparison">;
  unknownConstraints: string[];
  selected: boolean;
  selectable: boolean;
  onSelect: () => void;
}) {
  const compared = comparison
    ? Object.entries(comparison.rows)
        .map(([attribute, values]) => [attribute, values[product.product_id]] as const)
        .filter((entry): entry is readonly [string, string] => Boolean(entry[1]))
    : [];
  const caveats = [
    ...unknownConstraints,
    ...(product.stock.status === "out_of_stock" ? ["stock (reported out of stock)"] : []),
    ...(product.size_options === null ? ["size options"] : []),
  ];

  return (
    <article
      className={`rounded-2xl border p-5 transition-colors ${selected ? "border-emerald-400/55 bg-emerald-300/[0.055]" : "border-white/9 bg-white/[0.02] hover:border-white/16"}`}
    >
      <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-start">
        <div>
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <StatusBadge tone={product.provenance.snapshot ? "info" : "positive"}>
              {product.provenance.snapshot ? "Frozen snapshot" : "Live source"}
            </StatusBadge>
            {product.recommended ? (
              <StatusBadge tone="positive">Best recommendation</StatusBadge>
            ) : null}
            <span className="font-mono text-[0.65rem] text-slate-600">{product.product_id}</span>
          </div>
          <h3 className="text-lg font-semibold tracking-[-0.025em] text-white">{product.title}</h3>
          <p className="mt-1 text-xs text-slate-500">{product.brand ?? "Brand not shown"}</p>
          <p className="mt-2 text-2xl font-semibold text-emerald-200 tabular-nums">
            {money(product.price, product.currency)}
          </p>
          <p className="mt-1 text-xs text-slate-600">
            Catalog item price; use the verified quote below for checkout.
          </p>
        </div>
        <label
          className={`inline-flex min-h-10 items-center gap-2 rounded-lg border px-3 py-2 text-xs font-semibold ${selectable ? "border-white/10 text-slate-200" : "border-white/6 text-slate-600"}`}
        >
          <input
            type="radio"
            name="recommendation"
            checked={selected}
            disabled={!selectable}
            onChange={onSelect}
            className="accent-emerald-300"
          />
          {selectable ? "Select quoted item" : "Research candidate"}
        </label>
      </div>

      <div className="mt-5 grid gap-3 text-xs sm:grid-cols-3">
        <div className="min-w-0 rounded-lg border border-white/7 bg-black/15 p-3">
          <Database className="mb-2 size-3.5 text-cyan-300" aria-hidden="true" />
          <p className="text-slate-600">Source</p>
          <p className="mt-1 break-words text-slate-300">{product.provenance.source}</p>
          <p className="mt-1 break-all font-mono text-[0.62rem] text-slate-600">
            {product.provenance.source_id ?? "Source product ID unavailable"}
          </p>
        </div>
        <div className="min-w-0 rounded-lg border border-white/7 bg-black/15 p-3">
          <CalendarClock className="mb-2 size-3.5 text-cyan-300" aria-hidden="true" />
          <p className="text-slate-600">As of</p>
          <p className="mt-1 text-slate-300">
            {new Date(product.provenance.as_of).toLocaleString()}
          </p>
          <p className="mt-1 break-all font-mono text-[0.62rem] text-slate-600 [overflow-wrap:anywhere]">
            {product.provenance.catalog_manifest_hash ?? "Manifest hash unavailable"}
          </p>
        </div>
        <div className="min-w-0 rounded-lg border border-white/7 bg-black/15 p-3">
          <PackageSearch className="mb-2 size-3.5 text-amber-300" aria-hidden="true" />
          <p className="text-slate-600">Category / stock / size</p>
          <p className="mt-1 text-slate-300">{product.category}</p>
          <p className="mt-1 text-amber-100/80">
            {product.stock.status.replaceAll("_", " ")} ·{" "}
            {product.size_options?.join(", ") ?? "size unknown"}
          </p>
        </div>
      </div>

      <div className="mt-5 grid gap-4 lg:grid-cols-2">
        <div>
          <p className="font-mono text-[0.64rem] tracking-[0.1em] text-slate-600 uppercase">
            Why it matches
          </p>
          <p className="mt-2 text-sm leading-6 text-slate-300">
            {product.recommended
              ? "Selected as the best verified match after catalog research."
              : "Opened and compared during catalog research."}
          </p>
          {compared.length ? (
            <ul className="mt-2 space-y-1 text-xs text-slate-500">
              {compared.map(([attribute, value]) => (
                <li key={attribute}>
                  {attribute}: {value}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
        <div>
          <p className="flex items-center gap-2 font-mono text-[0.64rem] tracking-[0.1em] text-slate-600 uppercase">
            <CircleAlert className="size-3" aria-hidden="true" /> Why it might not
          </p>
          <p className="mt-2 text-sm leading-6 text-amber-100/65">
            {caveats.length
              ? `Unverified or limiting: ${[...new Set(caveats)].join(", ")}.`
              : "No explicit catalog caveat was returned."}
          </p>
        </div>
      </div>

      <details className="mt-5 border-t border-white/8 pt-4">
        <summary className="flex list-none items-center gap-2 text-xs font-semibold text-slate-300 [&::-webkit-details-marker]:hidden">
          <BookOpen className="size-3.5 text-emerald-300" aria-hidden="true" /> Review evidence (
          {reviews.length})
        </summary>
        {reviews.length ? (
          <div className="mt-3 space-y-3">
            {reviews.map((review) => (
              <blockquote
                key={review.review_id}
                className="rounded-xl border border-white/8 bg-black/15 p-4"
              >
                <p className="text-xs font-semibold text-emerald-200">{review.concern}</p>
                <p className="mt-1 text-sm leading-6 text-slate-300">{review.claim}</p>
                {review.excerpt ? (
                  <p className="mt-2 border-l border-emerald-300/30 pl-3 text-xs leading-5 text-slate-500">
                    “{review.excerpt}”
                  </p>
                ) : null}
                <footer className="mt-3 flex flex-wrap gap-2 text-[0.65rem] text-slate-500">
                  <span className="break-all font-mono text-cyan-300/70">{review.review_id}</span>
                  {review.source_review_id ? <span>source {review.source_review_id}</span> : null}
                  {review.rating !== null ? <span>{review.rating}/5 rating</span> : null}
                  {review.date ? <span>{review.date}</span> : null}
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
