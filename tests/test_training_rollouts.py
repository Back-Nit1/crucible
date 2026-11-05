"""One RolloutRecord per episode: every episode (survivor, loser, killed) is reusable rollout data."""
import pytest

from memory import InMemoryTraceRepository
from memory.episodes import episode_from_trace
from tests.fixtures.frozen import HASHES, SyntheticFrozen
from training.rollouts import RolloutRecord, group_id, rollout_from_episode
from world.runtime import build_population, run_generation
from world.store import GenerationStore, MemoryBlobStore
from world.taskgen import generate_tasks

SEED = 77


@pytest.fixture(scope="module")
def generation():
    cat = SyntheticFrozen()
    tasks, genomes = generate_tasks(cat, HASHES, seed=SEED, count=8, review_traps=1), build_population(8, SEED)
    traces = InMemoryTraceRepository()
    run_generation(generation_id="g-roll", seed=SEED, genomes=genomes, tasks=tasks, manifests=HASHES, catalog=cat,
                   store=GenerationStore(MemoryBlobStore()), traces=traces)
    return cat, {t.id: t for t in tasks}, {g.id: g for g in genomes}, [episode_from_trace(t) for t in traces.traces]


def build(generation, episode, **kw):
    cat, tasks, genomes, _ = generation
    return rollout_from_episode(episode, tasks[episode.task_id], genomes[episode.agent_id], catalog=cat,
                                policy_id="scripted-v1", **kw)


def test_every_episode_becomes_a_rollout_with_terminal_scores(generation):
    rollouts = [build(generation, ep, iteration_id="it-1") for ep in generation[3]]
    assert len(rollouts) == 64 and all(r.scripted for r in rollouts)  # scripted = pipeline evidence, flagged
    killed = [r for r in rollouts if r.killed]
    assert killed and all(r.kill_reasons and r.turns[-1].kill_rules == r.kill_reasons for r in killed)
    scored = [r for r in rollouts if r.fitness is not None]
    assert scored and all(r.gate in (0, 1) and r.quality is not None for r in scored)
    assert all(r.fitness is None and r.gate is None for r in rollouts if r.termination not in {"success", "no_match", "instant_kill"})
    r = scored[0]
    assert r.turns[0].messages[-1].role == "user" and r.turns[0].messages[-1].content == generation[1][r.task_id].raw_message
    assert len(r.turns[1].messages) == len(r.turns[0].messages) + 2  # prior call + its tool result
    assert all(t.schema_valid for t in r.turns) and r.adapter_hash is None and r.sample_index == 0


def test_rollout_is_deterministic_and_round_trips(generation):
    ep = generation[3][0]
    a, b = build(generation, ep, iteration_id="it-1"), build(generation, ep, iteration_id="it-1")
    assert a.model_dump_json() == b.model_dump_json()
    assert RolloutRecord.model_validate_json(a.model_dump_json()).model_dump_json() == a.model_dump_json()


def test_group_id_depends_on_task_checkpoint_and_iteration_only(generation):
    ep = generation[3][0]
    r = build(generation, ep, iteration_id="it-1", sample_index=3)
    assert r.group_id == group_id(ep.task_id, r.model_checkpoint, "it-1") == build(generation, ep, iteration_id="it-1").group_id
    assert r.group_id != group_id(ep.task_id, r.model_checkpoint, "it-2")
    assert r.group_id != group_id(ep.task_id, "qwen-base", "it-1")


def test_review_citations_mark_grounding_per_turn(generation):
    rollouts = [build(generation, ep) for ep in generation[3]]
    flags = {t.grounded for r in rollouts for t in r.turns if t.tool_call.name == "summarize_review_evidence"}
    assert True in flags
    assert {t.grounded for r in rollouts for t in r.turns if t.tool_call.name == "search_catalog"} == {None}
