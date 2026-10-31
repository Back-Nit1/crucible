"""Trace store + memory retrieval (spec 8.8). Agents depend on `TraceRepository`, never on Elastic."""
import re
from typing import Protocol

from pydantic import BaseModel


class TraceRecord(BaseModel):
    episode_id: str
    task_id: str
    agent_id: str
    generation: int = 0
    split: str  # train | val | test
    category: str = ""
    task_text: str  # raw shopper message; what similarity runs over
    killed: bool
    kill_reason: str | None = None
    fitness: float
    episode: dict = {}  # full episode JSON (tool calls, final answer, PayPal ids)


class TraceRepository(Protocol):
    def add(self, trace: TraceRecord) -> None: ...

    def similar(self, task_text: str, k: int = 3, min_fitness: float = 0.0) -> list[TraceRecord]:
        """Top-k best matches among traces with killed=false, fitness>=min_fitness and split != test."""


def eligible(t: TraceRecord, min_fitness: float) -> bool:
    return t.split != "test" and not t.killed and t.fitness >= min_fitness


_words = lambda s: set(re.findall(r"[a-z0-9]+", s.lower()))


class InMemoryTraceRepository:
    """Test double. Similarity = word-set Jaccard; ties broken by fitness."""

    def __init__(self):
        self.traces: list[TraceRecord] = []

    def add(self, trace: TraceRecord) -> None:
        self.traces = [t for t in self.traces if t.episode_id != trace.episode_id] + [trace]

    def similar(self, task_text: str, k: int = 3, min_fitness: float = 0.0) -> list[TraceRecord]:
        q = _words(task_text)
        jac = lambda t: len(q & _words(t.task_text)) / (len(q | _words(t.task_text)) or 1)
        pool = [t for t in self.traces if eligible(t, min_fitness)]
        return sorted(pool, key=lambda t: (-jac(t), -t.fitness))[:k]
