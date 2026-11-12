import type { ReactNode } from "react";

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow: string;
  title: string;
  description: string;
  actions?: ReactNode;
}) {
  return (
    <header className="mb-8 flex flex-col justify-between gap-6 border-b border-white/8 pb-7 lg:flex-row lg:items-end">
      <div className="max-w-3xl">
        <p className="mb-3 font-mono text-[0.68rem] tracking-[0.24em] text-emerald-300/75 uppercase">
          {eyebrow}
        </p>
        <h1 className="text-3xl leading-tight font-semibold tracking-[-0.045em] text-white sm:text-4xl">
          {title}
        </h1>
        <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-400 sm:text-base">
          {description}
        </p>
      </div>
      {actions ? <div className="flex shrink-0 flex-wrap items-center gap-3">{actions}</div> : null}
    </header>
  );
}
