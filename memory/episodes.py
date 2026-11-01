"""Boundary between the engine's EpisodeRecord and the Elastic `traces` document, plus the repository-backed
agents.memory.MemoryProvider (Elastic in production, in-memory in tests)."""
from __future__ import annotations

from decimal import Decimal

from agents.actions import (ConfirmAndPay, EpisodeRecord, GetProduct, ProposePurchase, SearchCatalog,
                            SummarizeReviewEvidence)
from agents.memory import RetrievalRequest
from memory import PROTECTED_SPLITS, TraceRecord, TraceRepository, eligible
from tasks.schemas import TaskSpec, TaskSplit


def _first(items):
    return list(dict.fromkeys(items))  # order-preserving de-duplication


def trace_from_episode(episode: EpisodeRecord, task: TaskSpec, genome=None, generation: int = 0) -> TraceRecord:
    """Lossless: `episode` holds the entire EpisodeRecord JSON; flat fields are derived views of it."""
    sc = episode.score_components
    scored = "fitness" in sc
    kills = [dict(k) for k in episode.kill_information]
    calls = episode.tool_calls
    payments = []
    for c in calls:
        if isinstance(c.action, ProposePurchase):
            payments.append({"event": "order_created", "sequence": c.sequence, "product_id": c.action.product_id,
                             "variant": c.action.variant, "amount": str(c.action.expected_total),
                             "refs": list(c.result_references), "error": c.error_code})
        elif isinstance(c.action, ConfirmAndPay):
            payments.append({"event": "captured", "sequence": c.sequence, "refs": list(c.result_references),
                             "summary": c.result_summary})
    return TraceRecord(
        episode_id=episode.episode_id, task_id=task.id, agent_id=episode.agent_id,
        generation=generation, generation_id=episode.generation_id, seed=episode.seed,
        split=task.split.value, category=task.hard_constraints.category, task_text=task.raw_message,
        catalog_hash=task.catalog_manifest_hash, killed=episode.killed,
        kill_reason=kills[0]["rule_id"] if kills else None,
        kill_rule_version=kills[0].get("rule_version") if kills else None, kills=kills,
        fitness=float(Decimal(str(sc["fitness"]))) if scored else 0.0, scored=scored,
        genome=genome.model_dump(mode="json") if genome is not None else {},
        products_considered=_first(r for c in calls if isinstance(c.action, (SearchCatalog, GetProduct))
                                   for r in c.result_references),
        review_ids_cited=_first(rid for c in calls if isinstance(c.action, SummarizeReviewEvidence)
                                for claim in c.action.claims for rid in claim.review_ids),
        payment_events=payments, score_components=dict(sc), final_answer=episode.final_answer,
        episode=episode.model_dump(mode="json"))


def episode_from_trace(trace: TraceRecord) -> EpisodeRecord:
    return EpisodeRecord.model_validate(trace.episode)


PRIVILEGED_CHECKPOINT_PREFIX = "scripted"  # scripted shoppers read the task's reference answer


def privileged(t: TraceRecord) -> bool:
    """A trace produced by a policy that saw reference answers. It is pipeline evidence, never retrievable as memory:
    a model prompt must not be able to inherit an answer key through a 'similar past episode'."""
    return str(t.genome.get("model_checkpoint", "")).startswith(PRIVILEGED_CHECKPOINT_PREFIX)


class RepositoryMemoryProvider:
    """agents.memory.MemoryProvider over any TraceRepository. `record` keeps every episode (dashboards, replay);
    `store` / `retrieve` enforce the memory rules: no test/held-out, killed, unscored or below-threshold traces."""

    def __init__(self, repo: TraceRepository):
        self.repo = repo

    def record(self, episode: EpisodeRecord, task: TaskSpec, genome=None, generation: int = 0) -> TraceRecord:
        trace = trace_from_episode(episode, task, genome, generation)
        self.repo.add(trace)
        return trace

    def store(self, episode: EpisodeRecord, *, split: TaskSplit, category: str, fitness: float,
              task: TaskSpec | None = None, genome=None, generation: int = 0) -> None:
        if task is None or split in {TaskSplit.TEST, TaskSplit.HELD_OUT_CATEGORY} or episode.killed or fitness < 0:
            return  # without the task the trace cannot carry its split/catalog provenance: not storable
        self.record(episode, task, genome, generation)

    def retrieve(self, request: RetrievalRequest) -> tuple[EpisodeRecord, ...]:
        if request.split.value in PROTECTED_SPLITS or request.k <= 0:
            return ()
        pool = self.repo.similar(request.query, k=max(12, request.k * 4), min_fitness=request.minimum_fitness)
        keep = [t for t in pool if eligible(t, request.minimum_fitness) and t.task_id != request.task_id and not privileged(t)]
        keep.sort(key=lambda t: (t.category != request.category, -t.fitness, t.episode_id))  # deterministic ties
        out = []
        for t in keep[: request.k]:
            try:
                out.append(episode_from_trace(t))
            except ValueError:
                continue  # malformed stored episode: fail closed
        return tuple(out)
