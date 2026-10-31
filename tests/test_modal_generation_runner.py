from decimal import Decimal

from catalog.taskgen import generate_tasks
from memory import InMemoryTraceRepository
from memory.checkpoints import CheckpointStore
from memory.provider import TraceMemoryProvider
from modal_app.generation_runner import run_generation
from tests.fixtures.snapshot import training_catalog
from world.evolution import initialize_population


def setup(tmp_path):
    cat = training_catalog()
    tasks = generate_tasks(cat, ["Cat"], 8, seed=4, snapshot_id="snap")
    mem = TraceMemoryProvider(InMemoryTraceRepository(), catalog_snapshot_id="snap", catalog_manifest_hash="h")
    return cat, tasks, mem, CheckpointStore(tmp_path), initialize_population(3, seed=2)


def run(tmp_path, **kw):
    cat, tasks, mem, store, genomes = setup(tmp_path)
    return run_generation(store=store, generation_id="gen-0", genomes=genomes, tasks=tasks, catalog=cat, memory=mem, seed=5, **kw), mem, store, genomes, tasks


def test_a_full_generation_runs_every_pair_once_and_selects_survivors(tmp_path):
    rep, mem, store, genomes, tasks = run(tmp_path)
    assert rep.complete and len(rep.executed) == len(set(rep.executed)) == len(genomes) * len(tasks)
    assert len(mem.repo.traces) == len(rep.executed) - len(rep.skipped)  # one trace per scored pair
    assert set(rep.fitness) <= {g.id for g in genomes} and rep.survivors and len(rep.next_generation) == len(genomes)
    assert store.load("gen-0").status == "complete"


def test_interrupted_run_resumes_only_remaining_pairs_without_duplicates(tmp_path):
    cat, tasks, mem, store, genomes = setup(tmp_path)
    first = run_generation(store=store, generation_id="gen-0", genomes=genomes, tasks=tasks, catalog=cat, memory=mem, seed=5, max_episodes=7)
    assert not first.complete and len(first.executed) == 7
    # a brand-new runner/process resumes from disk
    mem2 = TraceMemoryProvider(mem.repo, catalog_snapshot_id="snap", catalog_manifest_hash="h")
    second = run_generation(store=CheckpointStore(tmp_path), generation_id="gen-0", genomes=genomes, tasks=tasks, catalog=cat, memory=mem2, seed=5)
    assert second.complete and not set(first.executed) & set(second.executed)
    assert len(first.executed) + len(second.executed) == len(genomes) * len(tasks)
    ids = [t.episode_id for t in mem.repo.traces]
    assert len(ids) == len(set(ids))  # no duplicate traces


def test_resumed_result_equals_uninterrupted_result(tmp_path):
    full, *_ = run(tmp_path / "a")
    cat, tasks, mem, store, genomes = setup(tmp_path / "b")
    run_generation(store=store, generation_id="gen-0", genomes=genomes, tasks=tasks, catalog=cat, memory=mem, seed=5, max_episodes=5)
    done = run_generation(store=store, generation_id="gen-0", genomes=genomes, tasks=tasks, catalog=cat, memory=mem, seed=5)
    assert done.fitness == full.fitness and done.survivors == full.survivors and done.killed == full.killed


def test_only_mock_payments_are_used(tmp_path):
    rep, mem, *_ = run(tmp_path)
    assert all(t.provenance.get("cost") is not None for t in mem.repo.traces)
    assert not any("paypal" in str(t.episode).lower() for t in mem.repo.traces)


def test_fitness_is_the_mean_of_scored_episodes(tmp_path):
    rep, mem, store, genomes, tasks = run(tmp_path)
    g = next(iter(rep.fitness))
    mine = [Decimal(str(t.fitness)) for t in mem.repo.traces if t.agent_id == g]
    assert abs(rep.fitness[g] - sum(mine) / len(mine)) < Decimal("1e-9")
