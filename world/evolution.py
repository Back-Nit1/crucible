"""Seeded, resumable evolutionary selection without model calls."""

from __future__ import annotations

import hashlib
import json
import math
import random
from decimal import Decimal
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator


class WorldModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SearchParameters(WorldModel):
    query_reformulations: int = Field(default=1, ge=0, le=5)
    minimum_candidates: int = Field(default=2, ge=1, le=10)
    use_filters: bool = True


class ReviewStrategy(WorldModel):
    minimum_reviews: int = Field(default=2, ge=1, le=20)
    critical_fraction: Decimal = Field(default=Decimal("0.5"), ge=0, le=1)


class MemorySettings(WorldModel):
    enabled: bool = False
    k: int = Field(default=2, ge=1, le=10)


class MutationMetadata(WorldModel):
    seed: int = Field(ge=0)
    generation: int = Field(ge=0)
    changed_fields: tuple[str, ...] = ()
    proposer_version: str = Field(default="deterministic-v1", min_length=1)


class Genome(WorldModel):
    id: str = Field(min_length=1)
    system_prompt_variant: str = Field(min_length=1)
    search: SearchParameters
    reviews: ReviewStrategy
    memory: MemorySettings
    temperature: Decimal = Field(ge=0, le=2)
    model_checkpoint: str = Field(min_length=1)
    parent_id: str | None = None
    mutation: MutationMetadata | None = None


class GenerationSummary(WorldModel):
    generation_id: str
    seed: int = Field(ge=0)
    population_ids: tuple[str, ...]
    survivor_ids: tuple[str, ...]
    killed_ids: tuple[str, ...]
    best_fitness: Decimal | None = None
    mean_fitness: Decimal | None = None


class GenerationCheckpoint(WorldModel):
    schema_version: Literal["1.0"] = "1.0"
    generation_id: str
    seed: int = Field(ge=0)
    genomes: tuple[Genome, ...]
    task_ids: tuple[str, ...]
    completed_episode_keys: tuple[str, ...] = ()
    fitness: dict[str, Decimal] = Field(default_factory=dict)
    killed_agent_ids: tuple[str, ...] = ()
    status: Literal["running", "complete"] = "running"

    @model_validator(mode="after")
    def unique_references(self) -> GenerationCheckpoint:
        genome_ids = [genome.id for genome in self.genomes]
        if len(genome_ids) != len(set(genome_ids)):
            raise ValueError("checkpoint genome IDs must be unique")
        if len(self.completed_episode_keys) != len(set(self.completed_episode_keys)):
            raise ValueError("completed episodes cannot be duplicated")
        if not set(self.killed_agent_ids) <= set(genome_ids):
            raise ValueError("killed agent must exist in checkpoint population")
        return self

    def content_hash(self) -> str:
        payload = self.model_dump(mode="json")
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def remaining_episode_keys(self) -> tuple[str, ...]:
        completed = set(self.completed_episode_keys)
        return tuple(f"{genome.id}:{task_id}" for genome in self.genomes for task_id in self.task_ids
                     if f"{genome.id}:{task_id}" not in completed)


class MutationProposer(Protocol):
    version: str
    def propose_prompt(self, parent: Genome, seed: int) -> str: ...


class DeterministicMutationProposer:
    version = "deterministic-v1"
    def propose_prompt(self, parent: Genome, seed: int) -> str:
        suffixes = ("verify constraints", "cite review ids", "state assumptions")
        return f"{parent.system_prompt_variant} | {suffixes[seed % len(suffixes)]}"


def _genome_id(payload: dict[str, object]) -> str:
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:16]
    return f"genome-{digest}"


def genome_hash(genome: Genome) -> str:
    payload = genome.model_dump(mode="json", exclude={"id"})
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def initialize_population(size: int, seed: int, checkpoint: str = "qwen-base") -> tuple[Genome, ...]:
    if size < 1:
        raise ValueError("population size must be positive")
    rng = random.Random(seed)
    population = []
    for index in range(size):
        values = {
            "system_prompt_variant": f"grounded-shopper-v{1 + index % 3}",
            "search": SearchParameters(query_reformulations=rng.randint(0, 3),
                                       minimum_candidates=rng.randint(2, 5), use_filters=bool(rng.getrandbits(1))),
            "reviews": ReviewStrategy(minimum_reviews=rng.randint(2, 5),
                                      critical_fraction=Decimal(rng.randint(2, 8)) / Decimal(10)),
            "memory": MemorySettings(enabled=bool(rng.getrandbits(1)), k=rng.randint(2, 3)),
            "temperature": Decimal(rng.randint(0, 10)) / Decimal(10),
            "model_checkpoint": checkpoint,
            "parent_id": None,
            "mutation": None,
        }
        serialized = {key: value.model_dump(mode="json") if isinstance(value, BaseModel) else value
                      for key, value in values.items()}
        population.append(Genome(id=_genome_id({"seed": seed, "index": index, **serialized}), **values))
    return tuple(population)


def select_survivors(
    population: tuple[Genome, ...], fitness: dict[str, Decimal], killed_ids: set[str],
    cull_fraction: Decimal = Decimal("0.25"),
) -> tuple[Genome, ...]:
    eligible = [genome for genome in population if genome.id not in killed_ids]
    eligible.sort(key=lambda genome: (-fitness.get(genome.id, Decimal("-Infinity")), genome.id))
    keep = max(1, math.ceil(len(eligible) * float(Decimal(1) - cull_fraction))) if eligible else 0
    return tuple(eligible[:keep])


def tournament_parent(survivors: tuple[Genome, ...], fitness: dict[str, Decimal], rng: random.Random,
                      tournament_size: int = 3) -> Genome:
    if not survivors:
        raise ValueError("cannot select a parent from no survivors")
    contestants = rng.sample(list(survivors), min(tournament_size, len(survivors)))
    return min(contestants, key=lambda genome: (-fitness[genome.id], genome.id))


def mutate(parent: Genome, generation: int, seed: int, proposer: MutationProposer) -> Genome:
    rng = random.Random(seed)
    search = parent.search.model_copy(update={
        "query_reformulations": min(5, max(0, parent.search.query_reformulations + rng.choice((-1, 0, 1)))),
        "minimum_candidates": min(10, max(1, parent.search.minimum_candidates + rng.choice((-1, 0, 1)))),
    })
    reviews = parent.reviews.model_copy(update={
        "minimum_reviews": min(20, max(1, parent.reviews.minimum_reviews + rng.choice((-1, 0, 1)))),
        "critical_fraction": min(Decimal(1), max(Decimal(0),
            parent.reviews.critical_fraction + Decimal(rng.choice((-1, 0, 1))) / Decimal(10))),
    })
    temperature = min(Decimal(2), max(Decimal(0),
        parent.temperature + Decimal(rng.choice((-1, 0, 1))) / Decimal(10)))
    prompt = proposer.propose_prompt(parent, seed)
    values = dict(system_prompt_variant=prompt, search=search, reviews=reviews, memory=parent.memory,
                  temperature=temperature, model_checkpoint=parent.model_checkpoint, parent_id=parent.id,
                  mutation=MutationMetadata(seed=seed, generation=generation,
                      changed_fields=("system_prompt_variant", "search", "reviews", "temperature"),
                      proposer_version=proposer.version))
    return Genome(id=_genome_id({"parent": parent.id, "generation": generation, "seed": seed}), **values)


def breed_generation(
    survivors: tuple[Genome, ...], fitness: dict[str, Decimal], target_size: int,
    generation: int, seed: int, proposer: MutationProposer,
) -> tuple[Genome, ...]:
    if target_size < len(survivors):
        raise ValueError("target size cannot discard survivors")
    rng = random.Random(seed)
    result = list(survivors)  # elitism: all survivors remain unchanged
    used = {genome.id for genome in result}
    index = 0
    while len(result) < target_size:
        parent = tournament_parent(survivors, fitness, rng)
        child = mutate(parent, generation, seed + index + 1, proposer)
        index += 1
        if child.id not in used:
            result.append(child); used.add(child.id)
    return tuple(result)
