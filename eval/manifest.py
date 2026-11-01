"""Versioned, canonically hashed evaluation run manifest. Results from different manifests never merge."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from eval.contenders import ContenderConfig
from eval.publish import task_set_hash
from tasks.schemas import TaskSpec

MANIFEST_VERSION = "1.0"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RunStatus(StrEnum):
    PLANNED = "planned"
    RUNNING = "running"
    INTERRUPTED = "interrupted"
    COMPLETED = "completed"
    FAILED = "failed"


class ManifestTask(_Strict):
    id: str
    split: str
    category: str
    held_out_category: bool
    catalog_manifest_hash: str


class Versions(_Strict):
    prompt: str = Field(min_length=1)
    rules: str = Field(min_length=1)
    judge: str = Field(min_length=1)               # "none" when no semantic judge is used
    task_generator: str = Field(min_length=1)


class Resumability(_Strict):
    expected_records: int = Field(ge=0)
    completed_records: int = Field(default=0, ge=0)
    attempts: int = Field(default=0, ge=0)
    last_checkpoint_at: dt.datetime | None = None
    error: str | None = None


class EvaluationManifest(_Strict):
    manifest_version: Literal["1.0"] = MANIFEST_VERSION
    evaluation_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    created_at: dt.datetime
    tasks: tuple[ManifestTask, ...] = Field(min_length=1)      # exact execution order
    task_set_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    seeds: tuple[int, ...] = Field(min_length=1)               # exact seed set, ordered
    catalog_hash: str = Field(min_length=1)
    versions: Versions
    contenders: tuple[ContenderConfig, ...] = Field(min_length=1)
    memory_pool_hash: str | None = None                        # sha256 of the frozen memory pool; None = no pool
    memory_pool_size: int = Field(default=0, ge=0)
    pass_k: int = Field(ge=1)
    payment_backend: Literal["mock", "sandbox"] = "mock"
    # --- mutable run state: deliberately outside the identity hash ---
    status: RunStatus = RunStatus.PLANNED
    result_artifacts: dict[str, str] = Field(default_factory=dict)
    resume: Resumability

    @model_validator(mode="after")
    def coherent(self) -> EvaluationManifest:
        if self.created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
        for label, items in (("task ids", [t.id for t in self.tasks]), ("seeds", self.seeds),
                             ("contender ids", [c.id for c in self.contenders])):
            if len(items) != len(set(items)):
                raise ValueError(f"duplicate {label}")
        if len(self.seeds) < self.pass_k:
            raise ValueError("pass@k needs at least k distinct seeds per task")
        if any(c.prompt_version != self.versions.prompt for c in self.contenders):
            raise ValueError("every contender must use the manifest prompt version")
        if self.resume.expected_records != self.expected_records:
            raise ValueError("resume.expected_records disagrees with contenders x tasks x seeds")
        return self

    @property
    def expected_records(self) -> int:
        return len(self.contenders) * len(self.tasks) * len(self.seeds)

    @property
    def pairs(self) -> tuple[tuple[str, int], ...]:
        """The identical (task, seed) matrix every contender runs, in execution order."""
        return tuple((t.id, s) for t in self.tasks for s in self.seeds)

    @property
    def manifest_hash(self) -> str:
        identity = self.model_dump(mode="json", exclude={"status", "result_artifacts", "resume"})
        return hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def with_state(self, **changes) -> EvaluationManifest:
        return self.model_copy(update=changes)

    def verify_tasks(self, tasks: dict[str, TaskSpec]) -> tuple[TaskSpec, ...]:
        """Refuse to run when the supplied tasks are not exactly the planned ones."""
        ids = [t.id for t in self.tasks]
        missing = [i for i in ids if i not in tasks]
        if missing:
            raise ValueError(f"tasks missing for manifest: {missing[:5]}")
        picked = {i: tasks[i] for i in ids}
        if task_set_hash(picked) != self.task_set_hash:
            raise ValueError("task-set hash mismatch: tasks differ from the manifest")
        for planned in self.tasks:
            actual = picked[planned.id]
            if (actual.split.value, actual.catalog_manifest_hash) != (planned.split, planned.catalog_manifest_hash):
                raise ValueError(f"task {planned.id} split/catalog differs from the manifest")
        return tuple(picked[i] for i in ids)


def build_manifest(*, evaluation_id: str, tasks: tuple[TaskSpec, ...], seeds: tuple[int, ...],
                   contenders: tuple[ContenderConfig, ...], catalog_hash: str, versions: Versions, pass_k: int,
                   created_at: dt.datetime, payment_backend: str = "mock", memory_pool_hash: str | None = None,
                   memory_pool_size: int = 0) -> EvaluationManifest:
    return EvaluationManifest(
        evaluation_id=evaluation_id, created_at=created_at, seeds=seeds, contenders=contenders, catalog_hash=catalog_hash,
        versions=versions, pass_k=pass_k, payment_backend=payment_backend,
        memory_pool_hash=memory_pool_hash, memory_pool_size=memory_pool_size,
        tasks=tuple(ManifestTask(id=t.id, split=t.split.value, category=t.hard_constraints.category,
                                 held_out_category=t.held_out_category, catalog_manifest_hash=t.catalog_manifest_hash)
                    for t in tasks),
        task_set_hash=task_set_hash({t.id: t for t in tasks}),
        resume=Resumability(expected_records=len(contenders) * len(tasks) * len(seeds)))


def assert_same_manifest(*hashes: str) -> str:
    if len(set(hashes)) != 1:
        raise ValueError("refusing to merge results from different evaluation manifests")
    return hashes[0]
