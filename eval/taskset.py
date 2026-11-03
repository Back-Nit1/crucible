"""Product-disjoint evaluation task sets.

Root cause of the handoff's "5 protected-split feasible-set overlaps": world.taskgen builds every task over the WHOLE
category, so a test task and a train task with different budgets share every product cheaper than both. tasks.batch
filters each split's task pool to that split's own products; this module builds on it, adds verified review-trap plans
and returns (protected evaluation tasks, reference train/val tasks) that the leakage audit then verifies."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path

from catalog.providers.base import FrozenCatalogProvider
from eval.leakage import normalize
from tasks.batch import BatchConfig, ReviewTrapPlan, TaskBatch, generate_batch
from tasks.engine import SplitConfig
from tasks.schemas import TaskSpec, TaskSplit
from world.taskgen import MIN_REVIEWS, _signal, durability_reviews

PROTECTED = {TaskSplit.TEST, TaskSplit.HELD_OUT_CATEGORY}


def trap_plans(catalog: FrozenCatalogProvider, manifests: Mapping[str, str], categories) -> dict[str, tuple[ReviewTrapPlan, ...]]:
    """A plan for every (failing product, clean alternative) pair: any split pool can find a pair fully inside it."""
    out: dict[str, tuple[ReviewTrapPlan, ...]] = {}
    for cat in categories:
        products = sorted(catalog.iter_products(cat, manifests[cat]), key=lambda p: (p.price, p.id))
        clean = [p.id for p in products if len(catalog.get_reviews(p.id, None, 100)) >= MIN_REVIEWS
                 and not durability_reviews(catalog, p.id)]
        plans = []
        for p in products:
            bad = durability_reviews(catalog, p.id)
            if bad:
                signal = _signal(p.id, bad)
                plans.extend(ReviewTrapPlan(signal=signal, review_adjusted_best=alt) for alt in clean if alt != p.id)
        out[cat] = tuple(plans)
    return out


def build_eval_taskset(catalog: FrozenCatalogProvider, manifests: Mapping[str, str], *, seed: int, size: int,
                       held_out_categories: frozenset[str] = frozenset(), split: SplitConfig = SplitConfig(50, 10, 40),
                       review_trap_percent: int = 10, snapshot_id: str = "amazon2023-frozen") -> TaskBatch:
    cats = tuple(sorted(manifests))
    config = BatchConfig(size=size, categories=cats, held_out_categories=held_out_categories, split=split,
                         review_trap_percent=review_trap_percent)
    plans = trap_plans(catalog, manifests, cats) if review_trap_percent else None
    return generate_batch(catalog=catalog, snapshot_id=snapshot_id, manifests=manifests, seed=seed, config=config,
                          review_trap_plans=plans)


def partition(tasks: tuple[TaskSpec, ...]) -> tuple[tuple[TaskSpec, ...], tuple[TaskSpec, ...]]:
    """(protected evaluation tasks, reference train/val tasks)."""
    return (tuple(t for t in tasks if t.split in PROTECTED), tuple(t for t in tasks if t.split not in PROTECTED))


def dedupe_protected(protected: tuple[TaskSpec, ...], reference: tuple[TaskSpec, ...]
                     ) -> tuple[tuple[TaskSpec, ...], dict[str, str]]:
    """Drop protected tasks whose normalized request text already exists on a reference task or an earlier protected task.

    Why this is statistically valid: the rule looks only at the request text, never at difficulty, ground truth or any
    model outcome, so it cannot select easy or hard tasks. A text-identical pair is either the same query counted twice
    (same split, same pool, same budget) or a prompt the model/memory may have seen in training. Every drop is recorded."""
    seen = {normalize(t.raw_message): t.id for t in reference}
    kept, excluded = [], {}
    for t in protected:
        key = normalize(t.raw_message)
        if key in seen:
            excluded[t.id] = f"duplicate request text of {seen[key]}"
            continue
        seen[key] = t.id
        kept.append(t)
    return tuple(kept), excluded


def tasks_hash(tasks: tuple[TaskSpec, ...]) -> str:
    return hashlib.sha256(json.dumps([t.model_dump(mode="json") for t in tasks], sort_keys=True).encode()).hexdigest()


def write_tasks(path: str | Path, tasks: tuple[TaskSpec, ...]) -> str:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(t.model_dump_json() + "\n" for t in tasks))
    return tasks_hash(tasks)


def load_tasks(path: str | Path, expected_hash: str | None = None) -> tuple[TaskSpec, ...]:
    tasks = tuple(TaskSpec.model_validate_json(line) for line in Path(path).read_text().splitlines() if line.strip())
    if expected_hash is not None and tasks_hash(tasks) != expected_hash:
        raise ValueError(f"{path}: task content hash differs from the recorded hash")
    return tasks
