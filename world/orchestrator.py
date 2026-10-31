"""One-generation deterministic world orchestration over the frozen snapshot."""

from __future__ import annotations

import datetime as dt
from collections import Counter, defaultdict
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from agents.actions import EpisodeRecord
from agents.executor import InMemoryToolExecutor
from agents.memory import InMemoryMemoryProvider, MemoryProvider
from agents.model import AdapterPolicy, ModelAdapter
from agents.runner import run_episode
from eval.harness import EvaluationReport, calculate_metrics
from payments.guards import GuardedPayments
from payments.mock import MockPayments
from tasks.catalog import FrozenTrainingCatalog, require_frozen_training_catalog
from tasks.schemas import TaskSpec
from training.curation import CurationResult, curate_survivors
from world.evolution import GenerationCheckpoint, Genome, select_survivors


class OrchestratorModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GenerationRunSummary(OrchestratorModel):
    generation_id: str
    seed: int = Field(ge=0)
    episode_count: int = Field(ge=0)
    survivor_count: int = Field(ge=0)
    kills_by_rule: dict[str, int]
    wrong_refusals: int = Field(ge=0)
    hallucinations: int = Field(ge=0)
    review_grounding: Decimal | None
    review_trap_accuracy: Decimal | None
    mean_latency_ms: Decimal | None
    mock_payment_count: int = Field(ge=0)


class GenerationArtifacts:
    def __init__(self, *, checkpoint: GenerationCheckpoint, episodes: tuple[EpisodeRecord, ...],
                 summary: GenerationRunSummary, evaluation: EvaluationReport,
                 curation: CurationResult | None):
        self.checkpoint = checkpoint
        self.episodes = episodes
        self.summary = summary
        self.evaluation = evaluation
        self.curation = curation
        self.evaluation_json = evaluation.to_json()
        self.evaluation_markdown = evaluation.to_markdown()


def _episode_key(agent_id: str, task_id: str) -> str:
    return f"{agent_id}:{task_id}"


def _fitness(episode: EpisodeRecord) -> Decimal:
    value = episode.score_components.get("fitness")
    return Decimal(str(value)) if value is not None else Decimal("-1")


def run_generation(
    *, generation_id: str, seed: int, tasks: tuple[TaskSpec, ...], genomes: tuple[Genome, ...],
    catalog: FrozenTrainingCatalog, model: ModelAdapter,
    checkpoint: GenerationCheckpoint | None = None,
    existing_episodes: tuple[EpisodeRecord, ...] = (),
    memory: MemoryProvider | None = None, max_new_episodes: int | None = None,
    clock=None, created_at: dt.datetime | None = None,
) -> GenerationArtifacts:
    catalog = require_frozen_training_catalog(catalog)
    task_by_id = {task.id: task for task in tasks}
    genome_by_id = {genome.id: genome for genome in genomes}
    if len(task_by_id) != len(tasks) or len(genome_by_id) != len(genomes):
        raise ValueError("task and genome IDs must be unique")
    if any(task.catalog_snapshot_id != catalog.snapshot_id
           or task.catalog_manifest_hash != catalog.manifest_hash for task in tasks):
        raise ValueError("all generation tasks must bind to the supplied frozen snapshot")
    if any(not task.suitable_for_deterministic_training for task in tasks):
        raise ValueError("unknown-feasibility tasks cannot enter a deterministic generation")

    checkpoint = checkpoint or GenerationCheckpoint(
        generation_id=generation_id, seed=seed, genomes=genomes,
        task_ids=tuple(task.id for task in tasks),
    )
    if checkpoint.generation_id != generation_id or checkpoint.seed != seed:
        raise ValueError("checkpoint generation identity does not match this run")
    expected_keys = {_episode_key(genome.id, task.id) for genome in genomes for task in tasks}
    if not set(checkpoint.completed_episode_keys) <= expected_keys:
        raise ValueError("checkpoint contains a genome/task pair outside this generation")

    episodes = {_episode_key(item.agent_id, item.task_id): item for item in existing_episodes}
    if set(checkpoint.completed_episode_keys) != set(episodes):
        raise ValueError("resume requires exactly one persisted episode per completed checkpoint key")
    remaining = [key for key in checkpoint.remaining_episode_keys() if key in expected_keys]
    if max_new_episodes is not None:
        remaining = remaining[:max_new_episodes]

    backend = MockPayments(auto_approve=True)
    memory = memory or InMemoryMemoryProvider()
    for offset, key in enumerate(remaining):
        agent_id, task_id = key.split(":", 1)
        genome, task = genome_by_id[agent_id], task_by_id[task_id]
        episode_id = f"{generation_id}:{agent_id}:{task_id}"
        executor = InMemoryToolExecutor(
            catalog, GuardedPayments(backend, catalog), task_id=task.id, agent_id=agent_id,
            budget_cap=task.hard_constraints.max_total,
            min_candidates=task.research_requirements.min_candidates_compared,
            clock=clock,
        )
        policy = AdapterPolicy(
            model, request_id=episode_id, seed=seed + offset,
            system_prompt=genome.system_prompt_variant,
            model_checkpoint=genome.model_checkpoint,
        )
        episode = run_episode(
            episode_id=episode_id, task=task, agent_id=agent_id,
            generation_id=generation_id, policy=policy, executor=executor,
            seed=seed + offset, memory=memory, clock=clock,
        )
        episodes[key] = episode
        memory.store(episode, split=task.split, category=task.hard_constraints.category,
                     fitness=float(_fitness(episode)))

    ordered_episodes = tuple(episodes[key] for key in sorted(episodes))
    completed = tuple(sorted(episodes))
    by_agent: dict[str, list[EpisodeRecord]] = defaultdict(list)
    for episode in ordered_episodes:
        by_agent[episode.agent_id].append(episode)
    agent_fitness = {
        agent_id: sum((_fitness(episode) for episode in items), Decimal(0)) / Decimal(len(items))
        for agent_id, items in by_agent.items()
    }
    killed_agents = tuple(sorted(agent_id for agent_id, items in by_agent.items()
                                 if any(episode.killed for episode in items)))
    status = "complete" if len(completed) == len(expected_keys) else "running"
    checkpoint = GenerationCheckpoint(
        generation_id=generation_id, seed=seed, genomes=genomes,
        task_ids=tuple(task.id for task in tasks), completed_episode_keys=completed,
        fitness=agent_fitness, killed_agent_ids=killed_agents, status=status,
    )
    eligible_fitness = {genome.id: agent_fitness.get(genome.id, Decimal("-1")) for genome in genomes}
    survivors = select_survivors(genomes, eligible_fitness, set(killed_agents)) if agent_fitness else ()

    evaluation = calculate_metrics(ordered_episodes, task_by_id, pass_k=1)
    kills = Counter(item.get("rule_id", "UNKNOWN") for episode in ordered_episodes
                    for item in episode.kill_information)
    summary = GenerationRunSummary(
        generation_id=generation_id, seed=seed, episode_count=len(ordered_episodes),
        survivor_count=len(survivors), kills_by_rule=dict(sorted(kills.items())),
        wrong_refusals=int(evaluation.metrics["wrong_refusal_rate"].numerator),
        hallucinations=int(evaluation.metrics["hallucination_rate"].numerator),
        review_grounding=evaluation.metrics["review_grounding_rate"].value,
        review_trap_accuracy=evaluation.metrics["review_trap_accuracy"].value,
        mean_latency_ms=evaluation.metrics["latency_ms"].value,
        mock_payment_count=sum(bool(episode.payment_state.get("completed")) for episode in ordered_episodes),
    )
    curation = None
    if status == "complete":
        curation = curate_survivors(
            ordered_episodes, task_by_id, catalog, catalog_hash=catalog.manifest_hash,
            task_version="1.0", rule_version="initial-kill-rules-v1",
            created_at=created_at or (clock() if clock else dt.datetime.now(dt.timezone.utc)),
        )
    return GenerationArtifacts(checkpoint=checkpoint, episodes=ordered_episodes,
                               summary=summary, evaluation=evaluation, curation=curation)
