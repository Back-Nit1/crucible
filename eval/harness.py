"""Honest, denominator-aware evaluation of real episode records."""

from __future__ import annotations

import json
from collections import defaultdict
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from agents.actions import EpisodeRecord
from tasks.schemas import TaskSpec, TaskSplit


class EvalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Metric(EvalModel):
    numerator: Decimal
    denominator: Decimal
    excluded: int = Field(ge=0)
    unit: str = "rate"
    failure_reasons: dict[str, int] = Field(default_factory=dict)  # why numerator < denominator / why records were excluded

    @property
    def value(self) -> Decimal | None:
        return self.numerator / self.denominator if self.denominator else None


class EvaluationReport(EvalModel):
    report_version: str = "1.0"
    episode_count: int = Field(ge=0)
    configured_pass_k: int = Field(ge=1)
    metrics: dict[str, Metric]
    variance_across_seeds: dict[str, Decimal | None]   # population variance of the per-seed metric value; None = not computable
    seeds: tuple[int, ...] = ()

    def to_json(self) -> str:
        payload = self.model_dump(mode="json")
        payload["values"] = {name: str(metric.value) if metric.value is not None else None
                             for name, metric in self.metrics.items()}
        return json.dumps(payload, sort_keys=True, indent=2)

    def to_markdown(self) -> str:
        rows = ["| Metric | Numerator | Denominator | Excluded | Value |",
                "|---|---:|---:|---:|---:|"]
        for name, metric in sorted(self.metrics.items()):
            value = "N/A" if metric.value is None else str(metric.value)
            rows.append(f"| {name} | {metric.numerator} | {metric.denominator} | {metric.excluded} | {value} |")
        return "\n".join(("# Crucible evaluation report", "", *rows, ""))


def _kill(episode: EpisodeRecord, rule_id: str) -> bool:
    return any(item.get("rule_id") == rule_id for item in episode.kill_information)


def _quality(episode: EpisodeRecord, name: str) -> Decimal | None:
    for metric in episode.score_components.get("quality_metrics", []):
        if metric.get("name") == name:
            return Decimal(str(metric.get("value")))
    return None


def _rate(numerator: int | Decimal, denominator: int, total: int, unit: str = "rate",
          reasons: dict[str, int] | None = None) -> Metric:
    return Metric(numerator=Decimal(numerator), denominator=Decimal(denominator),
                  excluded=total - denominator, unit=unit, failure_reasons=dict(sorted((reasons or {}).items())))


def _failure_reasons(episodes) -> dict[str, int]:
    """Termination / kill-rule counts for episodes that did not succeed."""
    reasons: dict[str, int] = defaultdict(int)
    for episode in episodes:
        if _successful(episode):
            continue
        reasons[f"termination:{episode.termination}"] += 1
        for item in episode.kill_information:
            reasons[f"kill:{item.get('rule_id')}"] += 1
        if not episode.killed and episode.termination in {"success", "no_match"}:
            reasons["gate_failed"] += 1
    return reasons


def _successful(episode: EpisodeRecord) -> bool:
    return (not episode.killed and episode.termination in {"success", "no_match"}
            and episode.score_components.get("gate") in {1, "1"})


def calculate_metrics(
    episodes: tuple[EpisodeRecord, ...], tasks: dict[str, TaskSpec], *, pass_k: int = 4,
    include_variance: bool = True,
) -> EvaluationReport:
    total = len(episodes)
    known = [(episode, tasks.get(episode.task_id)) for episode in episodes]
    eligible = [(episode, task) for episode, task in known if task is not None]
    success = sum(_successful(episode) for episode, _ in eligible)
    metrics: dict[str, Metric] = {
        "success_rate": _rate(success, len(eligible), total, reasons=_failure_reasons(e for e, _ in eligible)),
        "hallucination_rate": _rate(sum(_kill(e, "K001_HALLUCINATED_PRODUCT") for e, _ in eligible), len(eligible), total),
        "budget_violation_rate": _rate(sum(_kill(e, "K003_BUDGET_VIOLATION") for e, _ in eligible), len(eligible), total),
    }

    gated = [(e, t) for e, t in eligible if "gate" in e.score_components]
    metrics["hard_constraint_satisfaction"] = _rate(
        sum(e.score_components.get("gate") in {1, "1"} for e, _ in gated), len(gated), total)
    impossible = [(e, t) for e, t in eligible if t.is_impossible]
    metrics["correct_refusal_rate"] = _rate(
        sum(e.termination == "no_match" and not e.killed for e, _ in impossible), len(impossible), total)
    feasible = [(e, t) for e, t in eligible if not t.is_impossible]
    metrics["wrong_refusal_rate"] = _rate(
        sum(e.refusal is not None or e.termination == "no_match" for e, _ in feasible), len(feasible), total)

    for output_name, metric_name in (
        ("intent_extraction_accuracy", "intent_extraction"),
        ("review_grounding_rate", "review_grounding"),
        ("persona_relevant_review_recall", "review_signal_recall"),
    ):
        values = [value for e, _ in eligible if (value := _quality(e, metric_name)) is not None]
        metrics[output_name] = _rate(sum(values, Decimal(0)), len(values), total)
    traps = [(e, t) for e, t in eligible if t.is_review_trap]
    trap_values = [value for e, _ in traps if (value := _quality(e, "review_trap_choice")) is not None]
    metrics["review_trap_accuracy"] = _rate(sum(trap_values, Decimal(0)), len(trap_values), total)

    by_task: dict[str, list[EpisodeRecord]] = defaultdict(list)
    for episode, _ in eligible:
        by_task[episode.task_id].append(episode)
    pass_groups = [sorted(items, key=lambda e: (e.seed, e.episode_id))[:pass_k]
                   for items in by_task.values() if len(items) >= pass_k]
    metrics[f"pass_at_{pass_k}"] = _rate(sum(any(_successful(e) for e in group) for group in pass_groups),
                                           len(pass_groups), len(by_task))
    held = [(e, t) for e, t in eligible if t.split is TaskSplit.HELD_OUT_CATEGORY]
    metrics["held_out_category_performance"] = _rate(sum(_successful(e) for e, _ in held), len(held), total)
    # Latency and cost come only from recorded model metadata. Episode timestamps are a synthetic deterministic clock and
    # an episode with no model steps (or unknown per-step cost) has no measurement: it is excluded, never counted as zero.
    timed = [e for e, _ in eligible if e.model_metadata and all("latency_ms" in m for m in e.model_metadata)]
    metrics["latency_ms"] = _rate(sum((sum((Decimal(str(m["latency_ms"])) for m in e.model_metadata), Decimal(0)) for e in timed),
                                      Decimal(0)), len(timed), total, "mean_ms_model_inference",
                                  reasons={"no_model_latency_recorded": len(eligible) - len(timed)} if len(eligible) > len(timed) else None)
    priced = [e for e in timed if all(m.get("cost_known") is not False for m in e.model_metadata)]
    metrics["cost_per_task"] = _rate(sum((e.cost for e in priced), Decimal(0)), len(priced), total, "mean_usd_list_rate_estimate",
                                     reasons={"cost_unknown": len(eligible) - len(priced)} if len(eligible) > len(priced) else None)

    variance: dict[str, Decimal | None] = {name: None for name in metrics}
    seeds = sorted({e.seed for e, _ in eligible})
    if include_variance and len(seeds) > 1:
        seed_reports = [calculate_metrics(tuple(e for e, _ in eligible if e.seed == seed), tasks,
                                          pass_k=pass_k, include_variance=False) for seed in seeds]
        for name in metrics:
            values = [report.metrics[name].value for report in seed_reports]
            valid = [value for value in values if value is not None]
            if len(valid) == len(values):
                mean = sum(valid, Decimal(0)) / Decimal(len(valid))
                variance[name] = sum(((value - mean) ** 2 for value in valid), Decimal(0)) / Decimal(len(valid))
    return EvaluationReport(episode_count=total, configured_pass_k=pass_k, metrics=metrics,
                            variance_across_seeds=variance, seeds=tuple(seeds))
