"""One resumable, scripted-model generation over the real frozen snapshot (Phase 6).

tasks (real products/reviews) -> genome x task episodes through the REAL action state machine, guards and scorer
(MockPayments only) -> traces to the trace repository (Elastic in production) + atomic checkpoint after every episode
-> cull/select -> Loophole Hunter proposals -> curated SFT manifest. Re-running the same generation id resumes: only
`remaining_episode_keys()` execute, trace ids are deterministic so nothing is duplicated."""
from __future__ import annotations

import datetime as dt
import json
import socket
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from agents.actions import EpisodeRecord
from agents.executor import InMemoryToolExecutor
from agents.memory import RetrievalRequest
from agents.runner import _trace, run_episode
from catalog.providers.base import FrozenCatalogProvider
from memory import TraceRepository
from memory.episodes import RepositoryMemoryProvider, episode_from_trace
from payments.guards import GuardedPayments
from payments.mock import MockPayments
from scoring.kill_rules import INITIAL_RULES
from tasks.schemas import TaskSpec, TaskSplit
from training.curation import curate_survivors
from world.evolution import (DeterministicMutationProposer, GenerationCheckpoint, Genome, breed_generation, genome_hash,
                             initialize_population)
from world.loophole_hunter import AuditEpisode, audit_generation
from world.scripted import FIXTURES, ScriptUnavailable, scripted_policy
from world.store import (Compat, EpisodeOutcome, GenerationState, GenerationStatus, GenerationStore, digest)
from world.taskgen import TASK_VERSION

BASE_TIME = dt.datetime(2026, 11, 1, tzinfo=dt.UTC)  # fixed clock: identical inputs give byte-identical traces
RULES_VERSION = ",".join(f"{r.id}:{r.version}" for r in INITIAL_RULES if r.enabled)


def build_population(size: int, seed: int, fixtures: bool = True) -> tuple[Genome, ...]:
    """Honest scripted genomes plus (when `fixtures`, size >= 6) one deliberate fixture agent per kill rule in FIXTURES."""
    n_fix = len(FIXTURES) if fixtures and size >= len(FIXTURES) + 2 else 0
    out = list(initialize_population(size - n_fix, seed, checkpoint="scripted-v1"))
    for variant, base in zip(sorted(FIXTURES), initialize_population(n_fix, seed + 1, checkpoint="scripted-v1") if n_fix else ()):
        gid = "genome-" + digest(variant, str(seed))[:16]
        out.append(Genome(id=gid, system_prompt_variant=variant, **{k: v for k, v in base.__dict__.items()
                                                                   if k not in {"id", "system_prompt_variant"}}))
    return tuple(out)


def compat_for(tasks: tuple[TaskSpec, ...], genomes: tuple[Genome, ...], manifests: dict[str, str]) -> Compat:
    return Compat(
        task_set_hash=digest(TASK_VERSION, *(f"{t.id}|{t.catalog_manifest_hash}|{t.hard_constraints.max_total}" for t in tasks)),
        catalog_hash=digest(*(f"{c}={h}" for c, h in sorted(manifests.items()))),
        rules_version=RULES_VERSION, population_hash=digest(*(genome_hash(g) for g in genomes)))


def make_clock(start: dt.datetime = BASE_TIME):
    t = [start]

    def tick() -> dt.datetime:
        t[0] += dt.timedelta(seconds=1)
        return t[0]
    return tick


@dataclass
class RunResult:
    generation_id: str
    state: GenerationState
    executed: list[str] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)  # episode key -> why no episode could be run
    inert_fixtures: list[str] = field(default_factory=list)
    complete: bool = False


def run_one(task: TaskSpec, genome: Genome, *, catalog: FrozenCatalogProvider, generation_id: str, seed: int,
            memory: RepositoryMemoryProvider | None) -> EpisodeRecord:
    agent_id, clock = genome.id, make_clock()
    policy = scripted_policy(task, catalog, genome, agent_id)
    backend = MockPayments()  # world runs NEVER touch PayPal sandbox
    executor = InMemoryToolExecutor(catalog, GuardedPayments(backend, catalog, clock=clock), task_id=task.id,
                                    agent_id=agent_id, budget_cap=task.hard_constraints.max_total,
                                    min_candidates=task.research_requirements.min_candidates_compared, clock=clock)
    return run_episode(episode_id=f"{generation_id}:{genome.id}:{task.id}", task=task, agent_id=agent_id,
                       generation_id=generation_id, policy=policy, executor=executor, seed=seed, clock=clock,
                       memory=memory if genome.memory.enabled else None)


def run_generation(*, generation_id: str, seed: int, genomes: tuple[Genome, ...], tasks: tuple[TaskSpec, ...],
                   manifests: dict[str, str], catalog: FrozenCatalogProvider, store: GenerationStore,
                   traces: TraceRepository, max_episodes: int | None = None, owner: str | None = None,
                   log=lambda msg: None) -> RunResult:
    fresh = GenerationState(compat=compat_for(tasks, genomes, manifests), checkpoint=GenerationCheckpoint(
        generation_id=generation_id, seed=seed, genomes=genomes, task_ids=tuple(t.id for t in tasks)))
    store.acquire(generation_id, owner or f"{socket.gethostname()}")
    memory, by_task, by_genome = RepositoryMemoryProvider(traces), {t.id: t for t in tasks}, {g.id: g for g in genomes}
    try:
        state = store.start_or_resume(generation_id, fresh)
        result = RunResult(generation_id, state)
        if state.status is GenerationStatus.COMPLETED:
            result.complete = True
            return result
        store.set_status(generation_id, GenerationStatus.RUNNING)
        for key in state.remaining():
            if max_episodes is not None and len(result.executed) + len(result.skipped) >= max_episodes:
                result.state = store.set_status(generation_id, GenerationStatus.INTERRUPTED)
                return result
            gid, tid = key.split(":", 1)
            genome, task = by_genome[gid], by_task[tid]
            try:
                try:
                    episode = run_one(task, genome, catalog=catalog, generation_id=generation_id, seed=seed, memory=memory)
                except ScriptUnavailable:
                    if genome.system_prompt_variant not in FIXTURES:
                        raise
                    # a fixture that cannot misbehave on this task behaves honestly instead (recorded, not hidden)
                    episode = run_one(task, genome.model_copy(update={"system_prompt_variant": "grounded-shopper-v1"}),
                                      catalog=catalog, generation_id=generation_id, seed=seed, memory=memory)
                    result.inert_fixtures.append(key)
            except ScriptUnavailable as e:
                result.skipped[key] = str(e)
                state = store.record_episode(generation_id, key, EpisodeOutcome(
                    episode_id=f"{generation_id}:{key}", fitness=Decimal(0), killed=False, termination="script_unavailable"))
                log(f"skip {key}: {e}")
                continue
            memory.record(episode, task, genome, generation=0)  # durable trace first, then the checkpoint
            sc = episode.score_components
            state = store.record_episode(generation_id, key, EpisodeOutcome(
                episode_id=episode.episode_id, fitness=Decimal(str(sc.get("fitness", "0"))), killed=episode.killed,
                kill_rules=tuple(k["rule_id"] for k in episode.kill_information), termination=episode.termination))
            result.executed.append(key)
            log(f"{len(state.checkpoint.completed_episode_keys)}/{len(state.checkpoint.genomes) * len(state.checkpoint.task_ids)} "
                f"{key} {episode.termination} fitness={sc.get('fitness', '-')} kills={[k['rule_id'] for k in episode.kill_information]}")
        result.state = store.finalize(generation_id)
        result.complete = True
        return result
    except KeyboardInterrupt:
        store.set_status(generation_id, GenerationStatus.INTERRUPTED)
        raise
    except Exception as e:
        if store.load(generation_id) is not None:
            store.set_status(generation_id, GenerationStatus.FAILED, error=type(e).__name__)  # class only: no messages/URLs
        raise
    finally:
        store.release(generation_id)


def audit_and_curate(*, result: RunResult, tasks: tuple[TaskSpec, ...], genomes: tuple[Genome, ...], traces: TraceRepository,
                     catalog: FrozenCatalogProvider, manifests: dict[str, str], breed_seed: int):
    """Post-generation: Loophole Hunter over the top survivors' traces, curated grounded SFT records, next population."""
    from types import SimpleNamespace
    state, by_task = result.state, {t.id: t for t in tasks}
    top = set(state.summary.survivor_ids[: max(1, len(state.summary.survivor_ids) // 2)])
    stored = traces.by_generation(result.generation_id)
    episodes = tuple(episode_from_trace(t) for t in stored)
    audits = []
    for ep in episodes:
        if ep.agent_id in top and ep.termination in {"success", "no_match"}:
            task = by_task[ep.task_id]
            audits.append(AuditEpisode(
                episode_id=ep.episode_id, task=task, trace=_trace(task, SimpleNamespace(records=list(ep.tool_calls))),
                persona_key=task.hard_constraints.category, parsed_field_count=3,
                search_signature=next((c.action.query for c in ep.tool_calls if c.action.type == "search_catalog"), "")))
    proposals = audit_generation(tuple(audits))
    curated = curate_survivors(episodes, by_task, catalog, catalog_hash=digest(*(f"{c}={h}" for c, h in sorted(manifests.items()))),
                               task_version=TASK_VERSION, rule_version=RULES_VERSION, created_at=BASE_TIME)
    fitness = {g: f for g, f in state.checkpoint.fitness.items()}
    survivors = tuple(g for g in genomes if g.id in state.summary.survivor_ids)
    next_pop = breed_generation(survivors, fitness, len(genomes), 1, breed_seed, DeterministicMutationProposer()) if survivors else ()
    return episodes, proposals, curated, next_pop
