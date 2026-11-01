import { AlertTriangle, DatabaseZap, RotateCcw } from "lucide-react";

export function EmptyState({ title, message }: { title: string; message: string }) {
  return (
    <div className="flex min-h-48 flex-col items-center justify-center px-6 py-10 text-center">
      <DatabaseZap className="size-7 text-slate-600" aria-hidden="true" />
      <h3 className="mt-4 text-sm font-semibold text-slate-200">{title}</h3>
      <p className="mt-2 max-w-md text-sm leading-6 text-slate-500">{message}</p>
    </div>
  );
}

export function ErrorState({
  title = "Data could not be loaded",
  message,
  onRetry,
}: {
  title?: string;
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div role="alert" className="rounded-xl border border-rose-800/60 bg-rose-950/20 p-5">
      <div className="flex gap-3">
        <AlertTriangle className="mt-0.5 size-5 shrink-0 text-rose-300" aria-hidden="true" />
        <div>
          <h3 className="font-semibold text-rose-100">{title}</h3>
          <p className="mt-1 text-sm leading-6 text-rose-200/70">{message}</p>
          {onRetry ? (
            <button
              type="button"
              onClick={onRetry}
              className="mt-4 inline-flex items-center gap-2 rounded-lg border border-rose-700/70 px-3 py-2 text-xs font-medium text-rose-100 hover:bg-rose-900/40"
            >
              <RotateCcw className="size-3.5" aria-hidden="true" /> Retry
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
}

export function LoadingBlock({ label = "Loading evidence" }: { label?: string }) {
  return (
    <div role="status" className="space-y-3 p-5" aria-label={label}>
      <span className="sr-only">{label}</span>
      {[78, 96, 62].map((width) => (
        <div
          key={width}
          className="h-3 animate-pulse rounded-full bg-white/7"
          style={{ width: `${width}%` }}
        />
      ))}
    </div>
  );
}
