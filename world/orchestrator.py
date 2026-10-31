"""Model-backed, MockPayments-only generation orchestration."""

from __future__ import annotations

import datetime as dt
import hashlib
from collections import Counter
from collections.abc import Callable
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from agents.actions import EpisodeRecord
from agents.executor import InMemoryToolExecutor
from agents.memory import MemoryProvider
from agents.model import AdapterPolicy, ModelAdapter
from agents.runner import run_episode
from catalog.providers.base import CatalogProvider
from eval.harness import EvaluationReport, calculate_metrics
from memory.adapter import episode_fitness
from memory.checkpoints import CheckpointStore
from payments.guards import GuardedPayments
from payments.mock import MockPayments
from tasks.schemas import TaskSpec
from world.evolution import (
    DeterministicMutationProposer,
    GenerationCheckpoint,
    Genome,
    breed_generation,
    select_survivors,
)

AdapterFactory = Callable[[TaskSpec, Genome], ModelAdapter]


class WorldContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GenerationRate(WorldContract):
    numerator: Decimal
    denominator: Decimal

    @property
    def value(self) -> Decimal | None:
        return self.numerator / self.denominator if self.denominator else None


class GenerationRunSummary(WorldContract):
    generation_id: str
    seed: int = Field(ge=0)
    population_size: int = Field(ge=0)
    task_count: int = Field(ge=0)
    episode_count: int = Field(ge=0)
    newly_executed_count: int = Field(ge=0)
    complete: bool
    survivor_count: int = Field(ge=0)
    killed_agent_count: int = Field(ge=0)
    kills_by_rule: dict[str, int]
    hallucination_rate: GenerationRate
    wrong_refusal_rate: GenerationRate
    correct_refusal_rate: GenerationRate
    review_grounding_rate: GenerationRate
    review_trap_accuracy: GenerationRate
    budget_violation_rate: GenerationRate
    mean_model_latency_ms: Decimal | None
    total_cost: Decimal
    mock_payment_count: int = Field(ge=0)


class GenerationRun(WorldContract):
    summary: GenerationRunSummary
    episodes: tuple[EpisodeRecord, ...]
    executed_keys: tuple[str, ...]
    fitness: dict[str, Decimal]
    killed_agent_ids: tuple[str, ...]
    survivor_ids: tuple[str, ...]
    next_generation: tuple[Genome, ...]
    evaluation: EvaluationReport | None = None


def _episode_seed(seed: int, key: str) -> int:
    return int.from_bytes(hashlib.sha256(f"{seed}|{key}".encode()).digest()[:4], "big")


def _quality(episode: EpisodeRecord, name: str) -> Decimal | None:
    for metric in episode.score_components.get("quality_metrics", []):
        if metric.get("name") == name:
            return Decimal(str(metric.get("value")))
    return None


def _killed_by(episode: EpisodeRecord, rule: str) -> bool:
    return any(item.get("rule_id") == rule for item in episode.kill_information)


def _summarize(
    generation_id: str,
    seed: int,
    genomes: tuple[Genome, ...],
    tasks: tuple[TaskSpec, ...],
    episodes: tuple[EpisodeRecord, ...],
    executed_count: int,
    complete: bool,
    survivors: tuple[Genome, ...],
    killed: tuple[str, ...],
) -> GenerationRunSummary:
    by_task = {task.id: task for task in tasks}
    feasible = [(episode, by_task[episode.task_id]) for episode in episodes if not by_task[episode.task_id].is_impossible]
    impossible = [(episode, by_task[episode.task_id]) for episode in episodes if by_task[episode.task_id].is_impossible]
    traps = [(episode, task) for episode, task in ((episode, by_task[episode.task_id]) for episode in episodes) if task.is_review_trap]
    grounding = [value for episode in episodes if (value := _quality(episode, "review_grounding")) is not None]
    trap_values = [value for episode, _ in traps if (value := _quality(episode, "review_trap_choice")) is not None]
    latencies = [
        Decimal(str(metadata["latency_ms"]))
        for episode in episodes
        for metadata in episode.model_metadata
        if metadata.get("latency_ms") is not None
    ]
    kills = Counter(
        str(item["rule_id"])
        for episode in episodes
        for item in episode.kill_information
        if "rule_id" in item
    )
    return GenerationRunSummary(
        generation_id=generation_id,
        seed=seed,
        population_size=len(genomes),
        task_count=len(tasks),
        episode_count=len(episodes),
        newly_executed_count=executed_count,
        complete=complete,
        survivor_count=len(survivors),
        killed_agent_count=len(killed),
        kills_by_rule=dict(sorted(kills.items())),
        hallucination_rate=GenerationRate(
            numerator=sum(_killed_by(episode, "K001_HALLUCINATED_PRODUCT") for episode in episodes),
            denominator=len(episodes),
        ),
        wrong_refusal_rate=GenerationRate(
            numerator=sum(episode.refusal is not None or episode.termination == "no_match" for episode, _ in feasible),
            denominator=len(feasible),
        ),
        correct_refusal_rate=GenerationRate(
            numerator=sum(episode.termination == "no_match" and not episode.killed for episode, _ in impossible),
            denominator=len(impossible),
        ),
        review_grounding_rate=GenerationRate(numerator=sum(grounding, Decimal(0)), denominator=len(grounding)),
        review_trap_accuracy=GenerationRate(numerator=sum(trap_values, Decimal(0)), denominator=len(trap_values)),
        budget_violation_rate=GenerationRate(
            numerator=sum(_killed_by(episode, "K003_BUDGET_VIOLATION") for episode in episodes),
            denominator=len(episodes),
        ),
        mean_model_latency_ms=(sum(latencies, Decimal(0)) / len(latencies)) if latencies else None,
        total_cost=sum((episode.cost for episode in episodes), Decimal(0)),
        mock_payment_count=sum(episode.payment_state.get("completed") is True for episode in episodes),
    )


def run_generation(
    *,
    store: CheckpointStore,
    generation_id: str,
    genomes: tuple[Genome, ...],
    tasks: tuple[TaskSpec, ...],
    catalog: CatalogProvider,
    memory: MemoryProvider,
    adapter_factory: AdapterFactory,
    seed: int,
    max_episodes: int | None = None,
    clock: Callable[[], dt.datetime] | None = None,
) -> GenerationRun:
    """Run or resume one generation; the only payment backend is MockPayments."""
    if not tasks or not genomes:
        raise ValueError("generation requires tasks and genomes")
    by_task = {task.id: task for task in tasks}
    by_genome = {genome.id: genome for genome in genomes}
    if len(by_task) != len(tasks) or len(by_genome) != len(genomes):
        raise ValueError("task and genome IDs must be unique")
    store.create(
        GenerationCheckpoint(
            generation_id=generation_id,
            seed=seed,
            genomes=genomes,
            task_ids=tuple(by_task),
        )
    )
    executed: list[str] = []
    for key in store.remaining(generation_id):
        if max_episodes is not None and len(executed) >= max_episodes:
            break
        genome_id, task_id = key.split(":", 1)
        genome, task = by_genome[genome_id], by_task[task_id]
        adapter = adapter_factory(task, genome)
        policy = AdapterPolicy(adapter, genome.system_prompt_variant, seed=_episode_seed(seed, key))
        backend = MockPayments(auto_approve=True)
        executor = InMemoryToolExecutor(
            catalog,
            GuardedPayments(backend, catalog),
            task_id=task.id,
            agent_id=genome.id,
            budget_cap=task.hard_constraints.max_total,
            min_candidates=genome.search.minimum_candidates,
            clock=clock,
        )
        episode = run_episode(
            episode_id=f"{generation_id}:{key}",
            task=task,
            agent_id=genome.id,
            generation_id=generation_id,
            policy=policy,
            executor=executor,
            seed=_episode_seed(seed, key),
            memory=memory if genome.memory.enabled else None,
            clock=clock,
        )
        fitness = episode_fitness(episode)
        memory.store(episode, split=task.split, category=task.hard_constraints.category, fitness=fitness)
        store.complete(
            generation_id,
            key,
            {
                "episode": episode.model_dump(mode="json"),
                "mock_payment_count": len(backend.ledger),
            },
        )
        executed.append(key)

    results = store.results(generation_id)
    episodes = tuple(
        EpisodeRecord.model_validate(result["episode"])
        for _, result in sorted(results.items())
    )
    checkpoint = store.load(generation_id)
    assert checkpoint is not None
    if checkpoint.remaining_episode_keys():
        summary = _summarize(
            generation_id, seed, genomes, tasks, episodes, len(executed), False, (), ()
        )
        return GenerationRun(
            summary=summary,
            episodes=episodes,
            executed_keys=tuple(executed),
            fitness={},
            killed_agent_ids=(),
            survivor_ids=(),
            next_generation=(),
        )

    fitness: dict[str, Decimal] = {}
    killed: list[str] = []
    for genome in genomes:
        own = [episode for episode in episodes if episode.agent_id == genome.id]
        fitness[genome.id] = sum(
            (Decimal(str(episode_fitness(episode))) for episode in own), Decimal(0)
        ) / len(own)
        if any(episode.killed for episode in own):
            killed.append(genome.id)
    store.finalize(generation_id, fitness, tuple(killed))
    survivors = select_survivors(genomes, fitness, set(killed))
    next_generation = (
        breed_generation(
            survivors,
            fitness,
            len(genomes),
            generation=1,
            seed=seed,
            proposer=DeterministicMutationProposer(),
        )
        if survivors
        else ()
    )
    evaluation = calculate_metrics(episodes, by_task, pass_k=1)
    summary = _summarize(
        generation_id,
        seed,
        genomes,
        tasks,
        episodes,
        len(executed),
        True,
        survivors,
        tuple(killed),
    )
    return GenerationRun(
        summary=summary,
        episodes=episodes,
        executed_keys=tuple(executed),
        fitness=fitness,
        killed_agent_ids=tuple(killed),
        survivor_ids=tuple(genome.id for genome in survivors),
        next_generation=next_generation,
        evaluation=evaluation,
    )
