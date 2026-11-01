"""Deterministic protected-split leakage audit. Pure functions over tasks, memory traces and training manifests.

A check with no input is reported `not_run` (never silently passed). The audit is the gate for evaluation: any
`fail` blocks a run. There is deliberately no exclusion list: leaking tasks must be regenerated, not hidden."""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping

from pydantic import BaseModel, ConfigDict, Field

from memory import PROTECTED_SPLITS, TraceRecord
from memory.episodes import privileged
from tasks.schemas import TaskSpec, TaskSplit
from training.curation import TrainingManifest

AUDIT_VERSION = "1.0"
PROTECTED = {TaskSplit.TEST, TaskSplit.HELD_OUT_CATEGORY}
CHECKS = ("task_id_collisions", "duplicate_messages", "product_overlap", "review_overlap", "category_overlap",
          "memory_eligibility", "training_source_leakage", "catalog_manifest_match")
MAX_ITEMS = 50


class CheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: str                       # pass | fail | not_run
    examined: int = 0
    violations: int = 0
    items: tuple[str, ...] = ()       # first MAX_ITEMS violations, sorted
    note: str | None = None


class AuditReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    audit_version: str = AUDIT_VERSION
    protected_task_ids: tuple[str, ...]
    reference_task_ids: tuple[str, ...]
    checks: dict[str, CheckResult]
    passed: bool = Field(description="True only when no check failed AND none was left not_run unless allowed")
    content_hash: str

    def to_json(self) -> str:
        return json.dumps(self.model_dump(mode="json"), sort_keys=True, indent=2)


def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def products_of(task: TaskSpec) -> set[str]:
    """Every product the task's ground truth or an agent's answer could touch."""
    out = set(task.feasible_set) | {s.product_id for s in task.review_signals}
    out |= {p for p in (task.closest_product_id, task.best_value_reference, task.review_adjusted_best) if p}
    return out


def _result(examined: int, bad: Iterable[str], note: str | None = None) -> CheckResult:
    bad = sorted(set(bad))
    return CheckResult(status="fail" if bad else "pass", examined=examined, violations=len(bad), items=tuple(bad[:MAX_ITEMS]),
                       note=note)


def _not_run(note: str) -> CheckResult:
    return CheckResult(status="not_run", note=note)


def audit(*, protected: tuple[TaskSpec, ...], reference: tuple[TaskSpec, ...] = (),
          memory_traces: tuple[TraceRecord, ...] | None = None,
          training_manifests: tuple[TrainingManifest, ...] | None = None,
          category_manifests: Mapping[str, str] | None = None,
          allow_not_run: frozenset[str] = frozenset()) -> AuditReport:
    """`protected` = the evaluation tasks; `reference` = every task that may feed training or memory (train/val)."""
    prot_ids = {t.id for t in protected}
    checks: dict[str, CheckResult] = {}

    # 1. task id collisions (inside the protected set, and against anything that can train)
    seen: dict[str, int] = {}
    for t in (*protected, *reference):
        seen[t.id] = seen.get(t.id, 0) + 1
    checks["task_id_collisions"] = _result(len(seen), (i for i, n in seen.items() if n > 1))

    # 2. normalized raw-message duplicates between protected and reference tasks (or protected vs protected, different id)
    by_msg: dict[str, set[str]] = {}
    for t in (*protected, *reference):
        by_msg.setdefault(normalize(t.raw_message), set()).add(t.id)
    dup = [f"{sorted(ids)}" for msg, ids in by_msg.items() if len(ids) > 1 and ids & prot_ids]
    checks["duplicate_messages"] = _result(len(by_msg), dup,
                                           "templated requests that normalize to the same text are indistinguishable to a model")

    # 3. product overlap: a protected task must share no product with any task of a different split
    leaks = []
    for p in protected:
        pp = products_of(p)
        for o in (*protected, *reference):
            shared = pp & products_of(o) if o.split != p.split else set()
            if shared:
                leaks.append(f"{p.id}({p.split.value}) x {o.id}({o.split.value}): {len(shared)} product(s), e.g. {sorted(shared)[0]}")
    checks["product_overlap"] = _result(len(protected), leaks)

    # 4. identical review ids shared by tasks of different splits (same-split tasks may share a signal)
    owners: dict[str, set[tuple[str, str]]] = {}
    for t in (*protected, *reference):
        for s in t.review_signals:
            for rid in s.supporting_review_ids:
                owners.setdefault(rid, set()).add((t.id, t.split.value))
    checks["review_overlap"] = _result(len(owners), (f"{rid} in {sorted(i for i, _ in who)}" for rid, who in owners.items()
                                                      if len({sp for _, sp in who}) > 1 and {i for i, _ in who} & prot_ids))

    # 5. category: held-out categories must not appear in any non-held-out task
    held = {t.hard_constraints.category for t in protected if t.split is TaskSplit.HELD_OUT_CATEGORY}
    others = [t for t in (*protected, *reference) if t.split is not TaskSplit.HELD_OUT_CATEGORY]
    checks["category_overlap"] = _result(len(held), (f"{t.id}: category {t.hard_constraints.category}" for t in others
                                                     if t.hard_constraints.category in held))

    # 6. memory retrieval eligibility
    if memory_traces is None:
        checks["memory_eligibility"] = _not_run("no memory pool supplied")
    else:
        prot_products = set().union(*(products_of(t) for t in protected)) if protected else set()
        prot_msgs = {normalize(t.raw_message) for t in protected}
        bad = []
        for tr in memory_traces:
            if tr.split in PROTECTED_SPLITS:
                bad.append(f"{tr.episode_id}: protected split {tr.split}")
            if tr.task_id in prot_ids:
                bad.append(f"{tr.episode_id}: trace of evaluation task {tr.task_id}")
            if normalize(tr.task_text) in prot_msgs:
                bad.append(f"{tr.episode_id}: task text equals an evaluation message")
            if privileged(tr):
                bad.append(f"{tr.episode_id}: scripted trace carries an answer key")
            shared = (set(tr.products_considered) | set(tr.episode.get("recommended_products", []))) & prot_products
            if shared:
                bad.append(f"{tr.episode_id}: touches evaluation product {sorted(shared)[0]}")
        checks["memory_eligibility"] = _result(len(memory_traces), bad)

    # 7. training manifests: sources must be non-protected splits and not evaluation tasks
    if training_manifests is None:
        checks["training_source_leakage"] = _not_run("no training manifest supplied")
    else:
        bad, n = [], 0
        for m in training_manifests:
            for ep in m.source_episode_ids:
                n += 1
                split = m.source_task_splits.get(ep)
                if split is None or split in PROTECTED:
                    bad.append(f"{ep}: source split {split}")
                if any(ep.endswith(f":{tid}") or ep == tid for tid in prot_ids):
                    bad.append(f"{ep}: episode of an evaluation task")
        checks["training_source_leakage"] = _result(n, bad)

    # 8. every task's catalog hash must match the declared category manifest hash
    if category_manifests is None:
        checks["catalog_manifest_match"] = _not_run("no category manifests supplied")
    else:
        bad = [f"{t.id}: {t.catalog_manifest_hash[:12]} != manifest[{t.hard_constraints.category}]"
               for t in (*protected, *reference) if category_manifests.get(t.hard_constraints.category) != t.catalog_manifest_hash]
        checks["catalog_manifest_match"] = _result(len(protected) + len(reference), bad)

    failed = any(c.status == "fail" for c in checks.values())
    missing = [n for n, c in checks.items() if c.status == "not_run" and n not in allow_not_run]
    body = {"protected": sorted(prot_ids), "reference": sorted(t.id for t in reference),
            "checks": {n: c.model_dump(mode="json") for n, c in checks.items()}}
    return AuditReport(protected_task_ids=tuple(sorted(prot_ids)), reference_task_ids=tuple(sorted(t.id for t in reference)),
                       checks=checks, passed=not failed and not missing,
                       content_hash=hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest())
