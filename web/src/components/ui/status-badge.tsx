import type { ReactNode } from "react";

export type StatusTone = "neutral" | "positive" | "warning" | "danger" | "info";

const tones: Record<StatusTone, string> = {
  neutral: "border-slate-700 bg-slate-900/60 text-slate-300",
  positive: "border-emerald-700/70 bg-emerald-950/60 text-emerald-200",
  warning: "border-amber-700/70 bg-amber-950/60 text-amber-200",
  danger: "border-rose-700/70 bg-rose-950/60 text-rose-200",
  info: "border-cyan-700/70 bg-cyan-950/60 text-cyan-200",
};

export function StatusBadge({
  children,
  tone = "neutral",
  dot = false,
}: {
  children: ReactNode;
  tone?: StatusTone;
  dot?: boolean;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-mono text-[0.68rem] leading-none tracking-[0.08em] uppercase ${tones[tone]}`}
    >
      {dot ? <span className="size-1.5 rounded-full bg-current" aria-hidden="true" /> : null}
      {children}
    </span>
  );
}
