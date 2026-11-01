import { AlertTriangle, Check, CircleHelp } from "lucide-react";

function display(value: unknown) {
  if (Array.isArray(value)) return value.map(String).join(", ");
  if (value && typeof value === "object") return JSON.stringify(value);
  if (value === null || value === undefined || value === "") return "Not provided";
  return String(value);
}

export function IntentPanel({
  intent,
  assumptions,
}: {
  intent: Record<string, unknown>;
  assumptions: string[];
}) {
  const fields = Object.entries(intent);
  return (
    <div className="space-y-5">
      <dl className="grid gap-x-5 gap-y-3 sm:grid-cols-2">
        {fields.length ? (
          fields.map(([key, value]) => (
            <div key={key} className="border-b border-white/7 pb-3">
              <dt className="font-mono text-[0.62rem] tracking-[0.1em] text-slate-600 uppercase">
                {key.replaceAll("_", " ")}
              </dt>
              <dd className="mt-1 text-sm text-slate-200">{display(value)}</dd>
            </div>
          ))
        ) : (
          <p className="text-sm text-slate-500">No structured intent fields were returned.</p>
        )}
      </dl>

      <div>
        <h3 className="flex items-center gap-2 text-xs font-semibold tracking-[0.08em] text-slate-300 uppercase">
          <CircleHelp className="size-3.5 text-amber-300" aria-hidden="true" /> Assumptions
        </h3>
        {assumptions.length ? (
          <ul className="mt-3 space-y-2">
            {assumptions.map((assumption) => (
              <li key={assumption} className="flex gap-2 text-sm leading-5 text-slate-400">
                <Check className="mt-0.5 size-3.5 shrink-0 text-emerald-300" aria-hidden="true" />
                {assumption}
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-2 text-sm text-slate-500">The model stated no assumptions.</p>
        )}
      </div>

      <div className="rounded-xl border border-amber-800/50 bg-amber-950/20 p-3 text-xs leading-5 text-amber-100/75">
        <p className="flex items-center gap-2 font-semibold text-amber-200">
          <AlertTriangle className="size-3.5" aria-hidden="true" /> Unknown remains unknown
        </p>
        <p className="mt-1">
          Stock, size, shipping, and tax are not inferred from missing fields. They must be explicitly
          verified before purchase.
        </p>
      </div>
    </div>
  );
}
