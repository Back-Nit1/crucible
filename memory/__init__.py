"""Trace store + memory retrieval (spec 8.8). Agents depend on `TraceRepository`, never on Elastic."""
import re
from typing import Protocol

from pydantic import BaseModel


# Splits whose traces must never be retrievable as memory (test leakage; held-out categories must stay unseen).
PROTECTED_SPLITS = frozenset({"test", "held_out_category"})


class TraceRecord(BaseModel):
    episode_id: str
    task_id: str
    agent_id: str
    generation: int = 0
    generation_id: str = ""
    split: str  # train | val | test | held_out_category
    category: str = ""
    task_text: str  # raw shopper message; what similarity runs over
    killed: bool
    kill_reason: str | None = None  # first kill rule id, if any
    kill_rule_ids: list[str] = []
    fitness: float
    termination: str = ""
    seed: int = 0
    catalog_snapshot_id: str = ""
    catalog_manifest_hash: str = ""
    calls: list[str] = []  # ordered tool-call names, for dashboards/filters
    provenance: dict = {}
    episode: dict = {}  # the complete EpisodeRecord JSON (ordered calls, args, result refs, payment ids)


class TraceRepository(Protocol):
    def add(self, trace: TraceRecord) -> None: ...

    def similar(self, task_text: str, k: int = 3, min_fitness: float = 0.0) -> list[TraceRecord]:
        """Top-k best matches among traces with killed=false, fitness>=min_fitness and split not protected."""

    def search(self, task_text: str, k: int, min_fitness: float) -> list[tuple[TraceRecord, float]]:
        """Like `similar` but with each hit's similarity score (higher = closer); callers re-sort deterministically."""


def eligible(t: TraceRecord, min_fitness: float) -> bool:
    return t.split not in PROTECTED_SPLITS and not t.killed and t.fitness >= min_fitness


_words = lambda s: set(re.findall(r"[a-z0-9]+", s.lower()))


class InMemoryTraceRepository:
    """Test double. Similarity = word-set Jaccard; ties broken by fitness."""

    def __init__(self):
        self.traces: list[TraceRecord] = []

    def add(self, trace: TraceRecord) -> None:
        self.traces = [t for t in self.traces if t.episode_id != trace.episode_id] + [trace]

    def search(self, task_text: str, k: int, min_fitness: float) -> list[tuple[TraceRecord, float]]:
        q = _words(task_text)
        jac = lambda t: len(q & _words(t.task_text)) / (len(q | _words(t.task_text)) or 1)
        pool = [(t, jac(t)) for t in self.traces if eligible(t, min_fitness)]
        return sorted(pool, key=lambda x: (-x[1], -x[0].fitness, x[0].episode_id))[:k]

    def similar(self, task_text: str, k: int = 3, min_fitness: float = 0.0) -> list[TraceRecord]:
        return [t for t, _ in self.search(task_text, k, min_fitness)]
