"""Frozen, read-only memory for evaluation. Evaluation episodes are never written back, and the pool is audited first."""
from __future__ import annotations

import dataclasses
import hashlib
import json

from agents.actions import EpisodeRecord
from agents.memory import RetrievalRequest
from eval.leakage import audit
from memory import InMemoryTraceRepository, TraceRecord
from memory.episodes import RepositoryMemoryProvider
from tasks.schemas import TaskSpec, TaskSplit


class MemoryLeakage(RuntimeError):
    """The memory pool would hand evaluation tasks (or their products) to the model."""


def pool_hash(pool: tuple[TraceRecord, ...]) -> str:
    return hashlib.sha256(json.dumps(sorted(t.episode_id for t in pool)).encode()).hexdigest()


class FrozenEvalMemory:
    """RepositoryMemoryProvider rules (no killed/unscored/scripted/protected traces) over an immutable pool.

    The stock provider refuses every query made on behalf of a test/held-out task, which would silently turn
    base+memory into base on exactly the protected tasks. Queries are therefore answered from the audited pool as if
    made by a train task; the pool itself can never contain protected splits, evaluation tasks or evaluation products."""

    def __init__(self, pool: tuple[TraceRecord, ...], protected: tuple[TaskSpec, ...]):
        report = audit(protected=protected, memory_traces=pool,
                       allow_not_run=frozenset({"training_source_leakage", "catalog_manifest_match"}))
        if report.checks["memory_eligibility"].status == "fail":
            raise MemoryLeakage("; ".join(report.checks["memory_eligibility"].items[:5]))
        repo = InMemoryTraceRepository()
        for trace in pool:
            repo.add(trace)
        self.pool_size, self._inner = len(pool), RepositoryMemoryProvider(repo)

    def store(self, *args, **kwargs) -> None:
        return None  # read-only

    def retrieve(self, request: RetrievalRequest) -> tuple[EpisodeRecord, ...]:
        return self._inner.retrieve(dataclasses.replace(request, split=TaskSplit.TRAIN))
