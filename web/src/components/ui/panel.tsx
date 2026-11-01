import type { HTMLAttributes, ReactNode } from "react";

export function Panel({ className = "", ...props }: HTMLAttributes<HTMLElement>) {
  return (
    <section
      className={`rounded-2xl border border-white/10 bg-[#0b1514]/88 shadow-[0_28px_80px_-48px_rgba(88,255,184,0.35)] backdrop-blur ${className}`}
      {...props}
    />
  );
}

export function PanelHeader({
  eyebrow,
  title,
  action,
  className = "",
}: {
  eyebrow?: string;
  title: string;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <header
      className={`flex flex-wrap items-start justify-between gap-4 border-b border-white/8 px-5 py-4 ${className}`}
    >
      <div>
        {eyebrow ? (
          <p className="mb-1 font-mono text-[0.65rem] tracking-[0.18em] text-emerald-300/70 uppercase">
            {eyebrow}
          </p>
        ) : null}
        <h2 className="text-base font-semibold tracking-[-0.015em] text-slate-100">{title}</h2>
      </div>
      {action}
    </header>
  );
}

export function PanelBody({ className = "", ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={`p-5 ${className}`} {...props} />;
}
