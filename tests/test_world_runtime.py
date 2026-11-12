"""Phase 6 offline: tasks -> scripted episodes through the real state machine/guards/scorer -> traces -> checkpoint/resume."""
import json
from collections import Counter

import pytest

from memory import InMemoryTraceRepository
from world import report
from world.runtime import audit_and_curate, build_population, run_generation
from world.scripted import FIXTURES
from world.store import FileBlobStore, GenerationStatus, GenerationStore, MemoryBlobStore
from world.taskgen import generate_tasks
from tests.fixtures.frozen import HASHES, SyntheticFrozen

SEED = 77


@pytest.fixture(scope="module")
def world():
    cat = SyntheticFrozen()
    return cat, generate_tasks(cat, HASHES, seed=SEED, count=8, review_traps=1), build_population(8, SEED)


def run(world, store, traces, **kw):
    cat, tasks, genomes = world
    return run_generation(generation_id="g-test", seed=SEED, genomes=genomes, tasks=tasks, manifests=HASHES, catalog=cat,
                          store=store, traces=traces, **kw)


def test_task_mix_is_real_feasible_impossible_and_review_sensitive(world):
    _, tasks, _ = world
    assert sum(t.is_impossible for t in tasks) == 2 and sum(t.is_review_trap for t in tasks) == 1
    assert all(t.suitable_for_deterministic_training and not t.hard_constraints.required_variant for t in tasks)
    trap = next(t for t in tasks if t.is_review_trap)
    assert trap.review_adjusted_best != trap.best_value_reference and trap.review_signals[0].supporting_review_ids
    assert tasks == generate_tasks(world[0], HASHES, seed=SEED, count=8, review_traps=1)  # deterministic


def test_population_has_honest_agents_and_one_fixture_per_kill_rule(world):
    variants = Counter(g.system_prompt_variant for g in world[2])
    assert all(variants[v] == 1 for v in FIXTURES) and len(world[2]) == 8
    assert len(build_population(8, SEED, fixtures=False)) == 8 and not any(
        g.system_prompt_variant in FIXTURES for g in build_population(8, SEED, fixtures=False))


def test_full_generation_survives_kills_fixtures_and_never_buys_badly(world):
    traces, store = InMemoryTraceRepository(), GenerationStore(MemoryBlobStore())
    res = run(world, store, traces)
    assert res.complete and res.state.status is GenerationStatus.COMPLETED and not res.skipped
    eps, proposals, curated, nxt = audit_and_curate(result=res, tasks=world[1], genomes=world[2], traces=traces,
                                                    catalog=world[0], manifests=HASHES, breed_seed=SEED)
    s = report.summarize(result=res, tasks=world[1], episodes=eps, proposals=proposals, curated=curated, next_pop=nxt, params={})
    assert s["episodes"]["completed"] == 64 == s["episodes"]["traced"] == len(traces.traces)
    items = s["tasks"]["items"]
    assert [i["id"] for i in items] == [t.id for t in world[1]]
    assert sum(i["impossible"] for i in items) == s["tasks"]["impossible"]
    assert all(isinstance(i["max_total"], str) for i in items)
    by = s["kills"]["by_rule"]
    assert {"K001_HALLUCINATED_PRODUCT", "K002_WRONG_REFUSAL", "K003_BUDGET_VIOLATION", "K008_REVIEW_GAMING"} <= set(by)
    assert s["safety"]["hallucinated_purchases"] == 0 and s["safety"]["budget_violations_charged"] == 0
    assert s["safety"]["budget_attempts_blocked"] > 0 and s["safety"]["correct_no_match_on_impossible"] > 0
    assert len(s["survivors"]) >= 1 and set(s["survivors"]).isdisjoint(s["kills"]["killed_agents"])
    assert len(curated.records) > 0 and all(r.split.value in {"train", "val"} for r in curated.records)  # never test/held-out
    assert len(nxt) == 8 and all(t.generation_id == "g-test" for t in traces.traces)
    assert all(t.catalog_hash and t.genome["id"] == t.agent_id for t in traces.traces)  # provenance on every trace
    assert json.dumps(s, sort_keys=True) == json.dumps(s, sort_keys=True)


def test_interrupt_then_resume_runs_each_pair_exactly_once_and_matches_an_uninterrupted_run(world, tmp_path):
    traces_a, store_a = InMemoryTraceRepository(), GenerationStore(FileBlobStore(tmp_path / "a"))
    first = run(world, store_a, traces_a, max_episodes=25)
    assert not first.complete and first.state.status is GenerationStatus.INTERRUPTED and len(first.executed) == 25
    assert len(traces_a.traces) == 25
    second = run(world, store_a, traces_a)  # same call = resume
    assert second.complete and len(second.executed) == 64 - 25 and not set(first.executed) & set(second.executed)
    assert len(traces_a.traces) == 64 == len({t.episode_id for t in traces_a.traces})  # no duplicates
    again = run(world, store_a, traces_a)  # completed generation is idempotent: nothing re-runs
    assert again.complete and again.executed == [] and len(traces_a.traces) == 64
    traces_b = InMemoryTraceRepository()
    full = run(world, GenerationStore(MemoryBlobStore()), traces_b)
    assert second.state.summary == full.state.summary and second.state.checkpoint.fitness == full.state.checkpoint.fitness
    assert [t.model_dump() for t in traces_a.traces] == [t.model_dump() for t in traces_b.traces]  # byte-identical traces


def test_a_crash_mid_generation_marks_failed_and_releases_the_lock(world):
    class Boom(InMemoryTraceRepository):
        def add(self, trace):
            raise RuntimeError("elastic down: https://secret.example")
    store = GenerationStore(MemoryBlobStore())
    with pytest.raises(RuntimeError):
        run(world, store, Boom())
    st = store.load("g-test")
    assert st.status is GenerationStatus.FAILED and st.error == "RuntimeError" and "secret" not in st.model_dump_json()
    run(world, store, InMemoryTraceRepository())  # lock released: a retry resumes (nothing was recorded for the failed pair)


def test_world_runs_use_mock_payments_only(world):
    import inspect
    import world.runtime as rt
    src = inspect.getsource(rt)
    assert "MockPayments()" in src and "SandboxPayments" not in src
