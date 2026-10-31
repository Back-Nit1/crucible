"""Consumer-side memory contract and leakage-safe in-memory reference implementation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from agents.actions import EpisodeRecord
from tasks.schemas import TaskSplit
from memory import TraceRecord, TraceRepository


@dataclass(frozen=True)
class RetrievalRequest:
    task_id: str
    split: TaskSplit
    category: str
    query: str
    k: int
    minimum_fitness: float


class MemoryProvider(Protocol):
    def store(self, episode: EpisodeRecord, *, split: TaskSplit, category: str, fitness: float,
              task_text: str | None = None) -> None: ...
    def retrieve(self, request: RetrievalRequest) -> tuple[EpisodeRecord, ...]: ...


class InMemoryMemoryProvider:
    def __init__(self) -> None:
        self._records: list[tuple[EpisodeRecord, TaskSplit, str, float]] = []

    def store(self, episode: EpisodeRecord, *, split: TaskSplit, category: str, fitness: float,
              task_text: str | None = None) -> None:
        if split is TaskSplit.TEST or episode.killed or fitness < 0:
            return
        self._records.append((episode, split, category, fitness))

    def retrieve(self, request: RetrievalRequest) -> tuple[EpisodeRecord, ...]:
        if request.split is TaskSplit.TEST or request.k <= 0:
            return ()
        eligible = [item for item in self._records
                    if item[1] is not TaskSplit.TEST and not item[0].killed
                    and item[3] >= request.minimum_fitness]
        eligible.sort(key=lambda item: (item[2] != request.category, -item[3], item[0].episode_id))
        return tuple(item[0] for item in eligible[:request.k])


class TraceRepositoryMemoryProvider:
    """Adapter to the integrated platform trace repository contract."""

    def __init__(self, repository: TraceRepository):
        self.repository = repository

    def store(self, episode: EpisodeRecord, *, split: TaskSplit, category: str, fitness: float,
              task_text: str | None = None) -> None:
        if split is TaskSplit.TEST or episode.killed or fitness < 0:
            return
        self.repository.add(TraceRecord(
            episode_id=episode.episode_id, task_id=episode.task_id, agent_id=episode.agent_id,
            split=split.value, category=category, task_text=task_text or episode.final_answer,
            killed=episode.killed,
            kill_reason=(episode.kill_information[0].get("rule_id")
                         if episode.kill_information else None),
            fitness=fitness, episode=episode.model_dump(mode="json"),
        ))

    def retrieve(self, request: RetrievalRequest) -> tuple[EpisodeRecord, ...]:
        if request.split is TaskSplit.TEST or request.k <= 0:
            return ()
        records = self.repository.similar(request.query, k=request.k,
                                          min_fitness=request.minimum_fitness)
        return tuple(EpisodeRecord.model_validate(record.episode) for record in records
                     if record.split != TaskSplit.TEST.value and not record.killed)
