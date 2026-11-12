import type { TrainingRun } from "@/lib/api/types";
import styles from "./observatory.module.css";

function Sparkline({ values }: { values: number[] }) {
  if (values.length < 2) return null;
  const min = Math.min(...values);
  const span = Math.max(...values) - min || 1;
  const points = values
    .map((v, i) => `${(i / (values.length - 1)) * 100},${28 - ((v - min) / span) * 26}`)
    .join(" ");
  return (
    <svg
      className={styles.sparkline}
      viewBox="0 0 100 30"
      preserveAspectRatio="none"
      aria-hidden="true"
    >
      <polyline points={points} fill="none" stroke="currentColor" strokeWidth="1.6" />
    </svg>
  );
}

function ago(iso: string | null) {
  if (!iso) return "unknown";
  const seconds = Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 1000));
  return seconds < 90 ? `${seconds}s ago` : `${Math.round(seconds / 60)} min ago`;
}

/** One live training run from training.live: model, algorithm, progress and the recent loss curve. */
export function TrainingCard({ run }: { run: TrainingRun }) {
  const step = run.step ?? 0;
  const total = run.total_steps ?? 0;
  const pct = total > 0 ? Math.min(100, (step / total) * 100) : 0;
  const model = run.base_model?.split("/").pop() ?? "Unknown model";
  return (
    <div className={styles.trainingCard} data-status={run.status ?? "unknown"}>
      <div className={styles.trainingHead}>
        <strong>{model}</strong>
        <span>{run.status ?? "unknown"}</span>
      </div>
      <small>
        {(run.algorithm ?? "?").toUpperCase()} · {run.gpu ?? "GPU ?"} · run{" "}
        {run.run_id.slice(0, 12)}
      </small>
      <div
        className={styles.progress}
        role="progressbar"
        aria-valuenow={step}
        aria-valuemax={total}
      >
        <span style={{ width: `${pct}%` }} />
      </div>
      <div className={styles.trainingStats}>
        <span>
          step <strong>{step}</strong>/{total || "?"}
        </span>
        <span>
          loss <strong>{run.loss?.toFixed(4) ?? "—"}</strong>
        </span>
        <span>updated {ago(run.updated_at)}</span>
      </div>
      <Sparkline values={run.losses ?? []} />
    </div>
  );
}
