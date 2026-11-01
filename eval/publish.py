"""Publish evaluation and checkpoint records to the `evaluations` / `checkpoints` Elastic indices that the API reads
(`/models/evaluations`, `/models/checkpoints`). Idempotent: documents are keyed by their id.

Nothing is invented here: an evaluation document is built from measured episodes (eval.comparison), and a checkpoint
document records only what exists. A `trained` checkpoint needs an artifact reference and evaluation ids; without a
training run only `base` (the pinned open model) and `planned` (a cost-bounded LoRA plan) records can exist."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from eval.comparison import ComparisonReport, ContenderRun, compare_contenders
from tasks.schemas import TaskSpec
from training.planning import LoRAPlan

INDEX_MAPPINGS = {
    "evaluations": {"properties": {
        "evaluation_id": {"type": "keyword"}, "contender_id": {"type": "keyword"}, "model": {"type": "keyword"},
        "checkpoint": {"type": "keyword"}, "split": {"type": "keyword"}, "seed": {"type": "long"},
        "task_set_hash": {"type": "keyword"}, "catalog_hash": {"type": "keyword"}, "prompt_version": {"type": "keyword"},
        "judge_version": {"type": "keyword"}, "training_manifest_hash": {"type": "keyword"}, "created_at": {"type": "date"},
        "metrics": {"type": "object", "enabled": False}, "failure_counts": {"type": "object", "enabled": False},
        "lineage": {"type": "object", "enabled": False}}},
    "checkpoints": {"properties": {
        "checkpoint_id": {"type": "keyword"}, "status": {"type": "keyword"}, "base_model": {"type": "keyword"},
        "base_revision": {"type": "keyword"}, "parent_checkpoint": {"type": "keyword"}, "training_manifest_hash": {"type": "keyword"},
        "created_at": {"type": "date"}, "plan": {"type": "object", "enabled": False}, "lineage": {"type": "object", "enabled": False}}},
}


class EvaluationContext(BaseModel):
    """Everything an evaluation must declare so two runs are comparable (and reproducible) later."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    model: str = Field(min_length=1)               # e.g. "Qwen/Qwen2.5-7B-Instruct"
    catalog_hash: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    judge_version: str = Field(min_length=1)       # "none" when no semantic judge was used
    seed: int = Field(ge=0)
    created_at: dt.datetime
    base_checkpoint: str = "qwen-base"


def _digest(*parts: object) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()


def task_set_hash(tasks: dict[str, TaskSpec]) -> str:
    return _digest(sorted((t.id, t.catalog_manifest_hash, str(t.hard_constraints.max_total), t.split.value) for t in tasks.values()))


def evaluation_docs(runs: tuple[ContenderRun, ...], tasks: dict[str, TaskSpec], ctx: EvaluationContext, *, pass_k: int = 1
                    ) -> list[tuple[str, dict]]:
    """One document per contender, all over the identical task/seed pairs (enforced by compare_contenders)."""
    report: ComparisonReport = compare_contenders(runs, tasks, pass_k=pass_k)
    by_run = {r.contender_id: r for r in runs}
    used = {e.task_id for r in runs for e in r.episodes}
    splits = sorted({tasks[t].split.value for t in used})
    out = []
    for c in report.contenders:
        eps = by_run[c.contender_id].episodes
        meta = [m for e in eps for m in e.model_metadata]
        doc = {
            "evaluation_id": f"{c.contender_id}:{ctx.seed}:{task_set_hash({t: tasks[t] for t in sorted(used)})[:12]}",
            "contender_id": c.contender_id, "model": ctx.model, "checkpoint": c.checkpoint, "memory_enabled": c.memory_enabled,
            "split": splits[0] if len(splits) == 1 else "mixed", "splits": splits, "seed": ctx.seed,
            "task_set_hash": task_set_hash({t: tasks[t] for t in sorted(used)}), "catalog_hash": ctx.catalog_hash,
            "prompt_version": ctx.prompt_version, "judge_version": ctx.judge_version,
            "training_manifest_hash": c.training_manifest_hash, "created_at": ctx.created_at.isoformat(), "pass_k": pass_k,
            "episode_count": len(eps),
            "metrics": {n: {"numerator": str(m.numerator), "denominator": str(m.denominator), "excluded": m.excluded,
                            "value": None if m.value is None else str(m.value), "unit": m.unit}
                        for n, m in sorted(c.evaluation.metrics.items())},
            "held_out_category_performance": (lambda m: None if m.value is None else str(m.value))(
                c.evaluation.metrics["held_out_category_performance"]),
            "latency_cost": {"model_steps": len(meta), "latency_ms_total": sum(int(m.get("latency_ms", 0)) for m in meta),
                             "cost_total": str(sum((e.cost for e in eps), Decimal(0))),
                             "cost_unknown_steps": sum(m.get("cost_known") is False for m in meta),
                             "denominator_episodes": len(eps)},
            "failure_counts": {"episodes": len(eps), "model_failure": sum(e.termination == "model_failure" for e in eps),
                               "malformed_action": sum(e.termination == "malformed_action" for e in eps),
                               "tool_limit": sum(e.termination == "tool_limit" for e in eps),
                               "killed": sum(e.killed for e in eps)},
            "lineage": {"base_checkpoint": ctx.base_checkpoint, "training_manifest_hash": c.training_manifest_hash,
                        "task_seed_pairs": len(report.task_seed_pairs)},
        }
        out.append((doc["evaluation_id"], doc))
    return out


def checkpoint_doc(*, checkpoint_id: str, base_model: str, base_revision: str, created_at: dt.datetime,
                   status: str = "base", parent_checkpoint: str | None = None, plan: LoRAPlan | None = None,
                   artifact_ref: str | None = None, evaluation_ids: tuple[str, ...] = ()) -> tuple[str, dict]:
    if status not in {"base", "planned", "trained"}:
        raise ValueError("status must be base, planned or trained")
    if status == "planned" and plan is None:
        raise ValueError("a planned checkpoint needs its LoRA plan")
    if status == "trained" and not (artifact_ref and evaluation_ids and plan):
        raise ValueError("a trained checkpoint needs its plan, an artifact reference and evaluation ids: none is invented")
    if status == "base" and (plan or parent_checkpoint):
        raise ValueError("a base checkpoint has no plan or parent")
    return checkpoint_id, {
        "checkpoint_id": checkpoint_id, "status": status, "base_model": base_model, "base_revision": base_revision,
        "parent_checkpoint": parent_checkpoint, "training_manifest_hash": plan.training_manifest_hash if plan else None,
        "created_at": created_at.isoformat(), "plan": plan.model_dump(mode="json") if plan else None,
        "artifact_ref": artifact_ref, "evaluation_ids": list(evaluation_ids),
        "lineage": {"chain": [x for x in (parent_checkpoint, checkpoint_id) if x]}}


def publish(es, index: str, docs: list[tuple[str, dict]]) -> int:
    """Create the index if missing (existing mappings are kept), then upsert by id."""
    try:
        es.call("PUT", f"/{es.ix(index)}", {"mappings": INDEX_MAPPINGS[index]})
    except Exception as e:  # already exists is fine, anything else is not
        if "resource_already_exists" not in str(e):
            raise
    return es.bulk(index, docs)
