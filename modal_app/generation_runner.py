"""Resumable generation runner: genomes x tasks -> episodes -> traces -> checkpoint -> survivors. Mock payments only.

Ordering per genome/task pair is run -> persist trace (idempotent upsert by episode_id) -> record in checkpoint, so a crash
between steps re-runs at most that one pair and rewrites the same trace id: at-least-once execution, exactly-once result.
The model is injected (`policy_factory`); the default is the scripted oracle shopper, so results exercise the pipeline and are
NOT agent performance. Aggregation (interim integration choice, for agent 2 to confirm): genome fitness = mean fitness over
its scored episodes; a genome is killed if any of its episodes tripped an instant-kill rule."""
import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from agents.executor import InMemoryToolExecutor
from agents.runner import ActionPolicy, run_episode
from catalog.providers.base import CatalogProvider
from memory.adapter import episode_fitness
from memory.checkpoints import CheckpointStore
from memory.provider import TraceMemoryProvider
from modal_app.scripted_shopper import ScriptUnavailable, scripted_policy
from payments.guards import GuardedPayments
from payments.mock import MockPayments
from tasks.schemas import TaskSpec
from world.evolution import (DeterministicMutationProposer, GenerationCheckpoint, Genome, breed_generation,
                             select_survivors)

PolicyFactory = Callable[[TaskSpec, Genome, CatalogProvider], ActionPolicy]


def default_policy(task: TaskSpec, genome: Genome, catalog: CatalogProvider) -> ActionPolicy:
    return scripted_policy(task, catalog, genome.id, min_candidates=genome.search.minimum_candidates,
                           review_limit=max(genome.reviews.minimum_reviews, 2))


def episode_seed(generation_seed: int, key: str) -> int:
    return int.from_bytes(hashlib.sha256(f"{generation_seed}|{key}".encode()).digest()[:4], "big")


@dataclass
class GenerationReport:
    generation_id: str
    executed: list[str]          # pairs run by THIS call (a resumed call lists only what was remaining)
    skipped: dict[str, str]      # pair -> reason the catalog could not support a grounded script
    complete: bool
    fitness: dict[str, Decimal]
    killed: tuple[str, ...]
    survivors: tuple[str, ...]
    next_generation: tuple[str, ...]


def run_generation(*, store: CheckpointStore, generation_id: str, genomes: tuple[Genome, ...], tasks: list[TaskSpec],
                   catalog: CatalogProvider, memory: TraceMemoryProvider, seed: int,
                   policy_factory: PolicyFactory = default_policy, max_episodes: int | None = None,
                   next_size: int | None = None) -> GenerationReport:
    by_task = {t.id: t for t in tasks}
    by_genome = {g.id: g for g in genomes}
    store.create(GenerationCheckpoint(generation_id=generation_id, seed=seed, genomes=genomes, task_ids=tuple(by_task)))
    executed: list[str] = []
    for key in store.remaining(generation_id):
        if max_episodes is not None and len(executed) >= max_episodes:
            break  # bounded slice (simulated interruption / time budget); the rest resumes later
        genome_id, task_id = key.split(":", 1)
        genome, task = by_genome[genome_id], by_task[task_id]
        try:
            policy = policy_factory(task, genome, catalog)
        except ScriptUnavailable as e:
            store.complete(generation_id, key, {"status": "skipped", "reason": str(e)})
            executed.append(key)
            continue
        payments = GuardedPayments(MockPayments(auto_approve=True), catalog)  # bulk runs never touch PayPal
        ex = InMemoryToolExecutor(catalog, payments, task_id=task.id, agent_id=genome.id,
                                  budget_cap=task.hard_constraints.max_total, min_candidates=genome.search.minimum_candidates)
        ep = run_episode(episode_id=f"{generation_id}:{key}", task=task, agent_id=genome.id, generation_id=generation_id,
                         policy=policy, executor=ex, seed=episode_seed(seed, key))
        fit = episode_fitness(ep)
        memory.store(ep, split=task.split, category=task.hard_constraints.category, fitness=fit)
        store.complete(generation_id, key, {"status": "scored", "episode_id": ep.episode_id, "fitness": str(fit),
                                            "killed": ep.killed, "termination": str(ep.termination),
                                            "kills": [k["rule_id"] for k in ep.kill_information]})
        executed.append(key)

    cp = store.load(generation_id)
    results = store.results(generation_id)
    skipped = {k: r["reason"] for k, r in results.items() if r["status"] == "skipped"}
    if cp.remaining_episode_keys():
        return GenerationReport(generation_id, executed, skipped, False, {}, (), (), ())
    fitness: dict[str, Decimal] = {}
    killed: list[str] = []
    for g in genomes:
        scored = [r for k, r in results.items() if k.startswith(f"{g.id}:") and r["status"] == "scored"]
        if scored:
            fitness[g.id] = sum((Decimal(r["fitness"]) for r in scored), Decimal(0)) / len(scored)
        if any(r["killed"] for r in scored):
            killed.append(g.id)
    cp = store.finalize(generation_id, fitness, tuple(killed))
    survivors = select_survivors(genomes, fitness, set(killed))
    nxt = breed_generation(survivors, fitness, next_size or len(genomes), 1, seed, DeterministicMutationProposer()) if survivors else ()
    return GenerationReport(generation_id, executed, skipped, True, fitness, tuple(killed),
                            tuple(g.id for g in survivors), tuple(g.id for g in nxt))
