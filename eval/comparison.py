"""Comparable held-out contender reports with no placeholder measurements."""

from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict, Field

from agents.actions import EpisodeRecord
from eval.harness import EvaluationReport, calculate_metrics
from tasks.schemas import TaskSpec


class ComparisonModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ContenderRun(ComparisonModel):
    contender_id: str = Field(min_length=1)
    checkpoint: str = Field(min_length=1)
    memory_enabled: bool
    training_manifest_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    episodes: tuple[EpisodeRecord, ...]


class ContenderResult(ComparisonModel):
    contender_id: str
    checkpoint: str
    memory_enabled: bool
    training_manifest_hash: str | None
    evaluation: EvaluationReport


class ComparisonReport(ComparisonModel):
    report_version: str = "1.0"
    pass_k: int = Field(ge=1)
    task_seed_pairs: tuple[tuple[str, int], ...]
    contenders: tuple[ContenderResult, ...]

    def to_json(self) -> str:
        return json.dumps(self.model_dump(mode="json"), sort_keys=True, indent=2)

    def to_markdown(self) -> str:
        metric_names = sorted({
            name for contender in self.contenders for name in contender.evaluation.metrics
        })
        rows = [
            "# Crucible contender comparison",
            "",
            f"Identical task/seed pairs: {len(self.task_seed_pairs)}. Configured pass@k: {self.pass_k}.",
            "",
            "| Contender | Checkpoint | Memory | Training manifest | " + " | ".join(metric_names) + " |",
            "|---|---|---:|---|" + "---:|" * len(metric_names),
        ]
        for contender in self.contenders:
            values = []
            for name in metric_names:
                metric = contender.evaluation.metrics.get(name)
                values.append("N/A" if metric is None or metric.value is None else str(metric.value))
            rows.append(
                f"| {contender.contender_id} | {contender.checkpoint} | "
                f"{'on' if contender.memory_enabled else 'off'} | "
                f"{contender.training_manifest_hash or 'none'} | " + " | ".join(values) + " |"
            )
        return "\n".join(rows) + "\n"


def compare_contenders(
    runs: tuple[ContenderRun, ...],
    tasks: dict[str, TaskSpec],
    *,
    pass_k: int,
) -> ComparisonReport:
    if not runs:
        raise ValueError("comparison requires measured contender runs")
    ids = [run.contender_id for run in runs]
    if len(ids) != len(set(ids)):
        raise ValueError("contender IDs must be unique")
    expected: tuple[tuple[str, int], ...] | None = None
    results: list[ContenderResult] = []
    for run in runs:
        pairs = tuple(sorted((episode.task_id, episode.seed) for episode in run.episodes))
        if expected is None:
            expected = pairs
        elif pairs != expected:
            raise ValueError("contenders must use identical task IDs and seeds")
        unknown = sorted({episode.task_id for episode in run.episodes} - set(tasks))
        if unknown:
            raise ValueError(f"contender has unknown tasks: {unknown}")
        results.append(
            ContenderResult(
                contender_id=run.contender_id,
                checkpoint=run.checkpoint,
                memory_enabled=run.memory_enabled,
                training_manifest_hash=run.training_manifest_hash,
                evaluation=calculate_metrics(run.episodes, tasks, pass_k=pass_k),
            )
        )
    return ComparisonReport(
        pass_k=pass_k,
        task_seed_pairs=expected or (),
        contenders=tuple(results),
    )
