import Link from "next/link";
import type { LearningRound } from "@/lib/api/types";
import styles from "./observatory.module.css";

const STAGES = ["generate", "curate", "audit", "plan", "train", "evaluate", "reenter"];

function who(round: LearningRound) {
  if (round.evidence === "pipeline_evidence_scripted_dry_run") return "scripted dry run";
  const policy = round.policy ?? "";
  if (policy.startsWith("model:")) return policy.split(":")[2] ?? "model";
  return policy || "unknown policy";
}

function pct(value: number | null) {
  return value === null ? "—" : `${Math.round(value * 100)}%`;
}

/** The learning loop round by round: who acted, how they scored, how far the round got. The bar chart is mean
 * fitness per round, the signal that says whether the agents improve. */
export function RoundsPanel({
  rounds,
  currentGeneration,
  playable,
}: {
  rounds: LearningRound[];
  currentGeneration: string;
  playable: Set<string>;
}) {
  const best = Math.max(0.01, ...rounds.map((round) => round.mean_fitness ?? 0));
  return (
    <div className={styles.rounds}>
      <div className={styles.roundChart} aria-label="Mean fitness per round">
        {rounds.map((round) => (
          <span
            key={round.iteration_id}
            title={`${round.iteration_id}: fitness ${round.mean_fitness?.toFixed(3) ?? "not measured"}`}
            style={{ height: `${Math.max(4, ((round.mean_fitness ?? 0) / best) * 100)}%` }}
            data-active={round.generation_id === currentGeneration}
            data-empty={round.mean_fitness === null}
          />
        ))}
      </div>
      <ol className={styles.roundList}>
        {rounds.map((round) => {
          const running = round.next_stage !== null && round.metrics_source !== "summary";
          const body = (
            <div className={styles.roundBody}>
              <div className={styles.roundHead}>
                <strong>{round.iteration_id}</strong>
                <span>
                  {running ? `live · ${round.next_stage}` : (round.next_stage ?? "complete")}
                </span>
              </div>
              <small>
                {who(round)} · {round.episodes} episodes
              </small>
              <div className={styles.roundStats}>
                <span>
                  fitness <strong>{round.mean_fitness?.toFixed(3) ?? "—"}</strong>
                </span>
                <span>
                  kills <strong>{pct(round.kill_rate)}</strong>
                </span>
                <span>
                  success <strong>{pct(round.success_rate)}</strong>
                </span>
              </div>
              <div className={styles.stageDots} aria-label="Round stages">
                {STAGES.map((stage) => (
                  <i
                    key={stage}
                    title={`${stage}: ${round.stages[stage] ?? "not started"}`}
                    data-status={round.stages[stage] ?? "none"}
                  />
                ))}
              </div>
              {round.produced_checkpoint ? (
                <small>trained → {round.produced_checkpoint}</small>
              ) : null}
            </div>
          );
          return (
            <li key={round.iteration_id} data-active={round.generation_id === currentGeneration}>
              {playable.has(round.generation_id) ? (
                <Link
                  className={styles.roundBody}
                  href={`/observatory?generation=${encodeURIComponent(round.generation_id)}`}
                >
                  {body}
                </Link>
              ) : (
                body
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
