import { asRecord } from "@/lib/records";

export function FitnessDistribution({ value }: { value: unknown }) {
  const rows = Object.entries(asRecord(value))
    .map(([agent, fitness]) => [agent, Number(fitness)] as const)
    .filter((row) => Number.isFinite(row[1]))
    .sort((a, b) => b[1] - a[1]);

  if (!rows.length) return <p className="text-sm text-slate-500">Fitness was not published.</p>;
  return (
    <div className="space-y-3" aria-label="Fitness by genome">
      {rows.map(([agent, fitness]) => (
        <div
          key={agent}
          className="grid grid-cols-[minmax(7rem,0.85fr)_minmax(8rem,2fr)_3rem] items-center gap-3"
        >
          <span className="truncate font-mono text-[0.65rem] text-slate-500" title={agent}>
            {agent}
          </span>
          <span className="h-2 overflow-hidden rounded-full bg-white/6">
            <span
              className="block h-full rounded-full bg-gradient-to-r from-emerald-500 to-emerald-200"
              style={{ width: `${Math.max(0, Math.min(1, fitness)) * 100}%` }}
            />
          </span>
          <span className="text-right font-mono text-[0.66rem] text-slate-300 tabular-nums">
            {fitness.toFixed(2)}
          </span>
        </div>
      ))}
    </div>
  );
}
