"""Trace store + memory retrieval (spec 8.8). Agents depend on `TraceRepository`, never on Elastic."""
import re
from heapq import nsmallest
from typing import Protocol

from pydantic import BaseModel


class TraceRecord(BaseModel):
    """One episode as stored in the `traces` index. Flat fields drive filters/dashboards; `episode` is the complete
    source EpisodeRecord JSON (ordered tool calls, args, result refs, timestamps, final answer, score, kills)."""
    schema_version: str = "2"
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
    generation_id: str = ""
    seed: int | None = None
    catalog_hash: str | None = None  # TaskSpec.catalog_manifest_hash the episode ran against
    genome: dict = {}  # complete Genome JSON (None-safe: empty for non-world traces)
    scored: bool = False  # True only when the episode ran to a scored terminal action; unscored never retrievable
    kill_rule_version: int | None = None
    kills: list[dict] = []  # every KillDecision: rule_id, rule_version, description, evidence
    products_considered: list[str] = []
    review_ids_cited: list[str] = []
    payment_events: list[dict] = []  # PayPal/mock order + capture ids, amounts
    score_components: dict = {}
    final_answer: str = ""


class TraceRepository(Protocol):
    def add(self, trace: TraceRecord) -> None: ...

    def similar(self, task_text: str, k: int = 3, min_fitness: float = 0.0) -> list[TraceRecord]:
        """Top-k best matches among traces with killed=false, fitness>=min_fitness and split != test."""

    def by_generation(self, generation_id: str) -> list[TraceRecord]:
        """Every stored trace of one generation (all splits, killed or not), ordered by episode_id."""


PROTECTED_SPLITS = ("test", "held_out_category")  # never retrievable: they would leak evaluation tasks into memory


def eligible(t: TraceRecord, min_fitness: float) -> bool:
    return t.split not in PROTECTED_SPLITS and not t.killed and t.scored and t.fitness >= min_fitness


_words = lambda s: set(re.findall(r"[a-z0-9]+", s.lower()))


class InMemoryTraceRepository:
    """Test double. Similarity = word-set Jaccard; ties broken by fitness."""

    def __init__(self):
        self.traces: list[TraceRecord] = []

    def add(self, trace: TraceRecord) -> None:
        self.traces = [t for t in self.traces if t.episode_id != trace.episode_id] + [trace]

    def similar(self, task_text: str, k: int = 3, min_fitness: float = 0.0) -> list[TraceRecord]:
        q = _words(task_text)
        def rank(t):
            words = _words(t.task_text)
            overlap = len(q & words)
            return (-overlap / (len(q) + len(words) - overlap or 1), -t.fitness)

        pool = (t for t in self.traces if eligible(t, min_fitness))
        # Preserve Python slicing semantics for legacy callers passing a negative k.
        return sorted(pool, key=rank)[:k] if k < 0 else nsmallest(k, pool, key=rank)

    def by_generation(self, generation_id: str) -> list[TraceRecord]:
        return sorted((t for t in self.traces if t.generation_id == generation_id), key=lambda t: t.episode_id)
