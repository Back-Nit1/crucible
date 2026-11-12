import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";
import type { ReactNode } from "react";

export function MetricCard({
  label,
  value,
  detail,
  trend,
  icon,
}: {
  label: string;
  value: ReactNode;
  detail?: ReactNode;
  trend?: "up" | "down" | "flat";
  icon?: ReactNode;
}) {
  const TrendIcon = trend === "up" ? ArrowUpRight : trend === "down" ? ArrowDownRight : Minus;
  return (
    <article className="group relative overflow-hidden rounded-xl border border-white/9 bg-white/[0.025] p-4">
      <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-emerald-300/30 to-transparent opacity-0 transition-opacity group-hover:opacity-100" />
      <div className="flex items-center justify-between gap-3 text-slate-400">
        <p className="font-mono text-[0.67rem] tracking-[0.12em] uppercase">{label}</p>
        {icon}
      </div>
      <div className="mt-3 flex items-end justify-between gap-3">
        <p className="text-2xl font-semibold tracking-[-0.04em] text-slate-50 tabular-nums">
          {value}
        </p>
        {trend ? <TrendIcon className="mb-1 size-4 text-slate-500" aria-hidden="true" /> : null}
      </div>
      {detail ? <div className="mt-2 text-xs leading-5 text-slate-500">{detail}</div> : null}
    </article>
  );
}
