"""Runner: identical matrix, atomic artifacts, resumption without duplicates, breaker, finalize refusal, memory rules.
The scripted model double reads answer keys: these tests check machinery, never model quality."""
import datetime as dt
import json
from decimal import Decimal

import pytest

from agents.actions import ConfirmAndPay, ProposePurchase
from agents.model import ScriptedModelAdapter
from eval.contenders import ContenderConfig, standard_contenders
from eval.manifest import RunStatus, Versions, build_manifest
from eval.memory import FrozenEvalMemory, MemoryLeakage, pool_hash
from eval.runner import EvaluationStore, Incomplete, contender_genome, finalize, run_evaluation
from eval.taskset import build_eval_taskset, dedupe_protected, partition
from memory.episodes import trace_from_episode
from payments.guards import idempotency_key
from tests.fixtures.eval_catalog import HASHES, BigSynthetic
from world.scripted import build_script

NOW = dt.datetime(2026, 11, 1, tzinfo=dt.UTC)
REV, EVAL = "a" * 40, "ev-test"
VERSIONS = Versions(prompt="shopper-prompts-v1", rules="K001:1", judge="none", task_generator="taskgen-v1")
SEEDS = (11, 12)


@pytest.fixture(scope="module")
def world():
    cat = BigSynthetic()
    batch = build_eval_taskset(cat, HASHES, seed=7, size=60, held_out_categories=frozenset({"gizmos"}))
    protected, reference = partition(batch.tasks)
    protected, _ = dedupe_protected(protected, reference)
    return cat, protected[:4], reference


def contenders(memory_k=2):
    return tuple(c for c in standard_contenders(model_id="Qwen/Qwen2.5-7B-Instruct", base_revision=REV, prompt_version="shopper-prompts-v1",
                                               endpoint="test:double", memory_k=memory_k) if not c.memory_enabled)


def scripts_for(cat, tasks, cs, eval_id=EVAL, seeds=SEEDS):
    out = {}
    for c in cs:
        for t in tasks:
            steps = build_script(t, cat, contender_genome(c))
            buy = next((s for s in steps if isinstance(s, ProposePurchase)), None)
            if buy:
                steps.append(ConfirmAndPay(pending_order_id=idempotency_key(t.id, c.id, buy.product_id, buy.variant), user_confirmed=True))
            for s in seeds:
                out[f"{eval_id}:{c.id}:{t.id}:s{s}"] = tuple(steps)
    return out


def setup(world, cs=None, seeds=SEEDS, eval_id=EVAL, **kw):
    cat, tasks, _ = world
    cs = cs or contenders()
    manifest = build_manifest(evaluation_id=eval_id, tasks=tasks, seeds=seeds, contenders=cs, catalog_hash="c" * 64,
                              versions=VERSIONS, pass_k=1, created_at=NOW, **kw)
    adapter = ScriptedModelAdapter(scripts_for(cat, tasks, cs, eval_id, seeds))
    return cat, {t.id: t for t in tasks}, manifest, adapter


def go(world, tmp_path, **kw):
    run_kw = {k: kw.pop(k) for k in ("max_workers", "max_episodes", "memory", "adapter") if k in kw}
    cat, tasks, manifest, adapter = setup(world, **kw)
    adapter = run_kw.pop("adapter", adapter)
    out = run_evaluation(manifest, tasks, catalog=cat, model_factory=lambda c: adapter, store=EvaluationStore(tmp_path, EVAL), **run_kw)
    return manifest, out, adapter


def episodes_json(manifest, tmp_path):
    return {k: json.loads(a.episode.model_dump_json()) for k, a in EvaluationStore(tmp_path, EVAL).load_episodes(manifest).items()}


def test_every_contender_runs_the_identical_task_seed_matrix(world, tmp_path):
    manifest, out, _ = go(world, tmp_path)
    assert out.complete and out.unique_records == manifest.expected_records == 1 * 4 * 2
    runs = finalize(manifest, EvaluationStore(tmp_path, EVAL))
    pairs = {cid: sorted((e.task_id, e.seed) for e in eps) for cid, eps in runs.items()}
    assert len({tuple(p) for p in pairs.values()}) == 1 and pairs["base-qwen"] == sorted(manifest.pairs)
    ids = [e.episode_id for eps in runs.values() for e in eps]
    assert len(ids) == len(set(ids))                              # seed is part of the episode id
    assert EvaluationStore(tmp_path, EVAL).load_manifest().status is RunStatus.COMPLETED
    assert not list(tmp_path.rglob(".tmp-*"))                      # atomic writes leave no temp files


def test_resume_executes_only_the_missing_records_and_matches_an_uninterrupted_run(world, tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    m, first, adapter = go(world, a, max_episodes=3)
    assert not first.complete and first.executed == 3 and first.status is RunStatus.INTERRUPTED
    with pytest.raises(Incomplete, match="expected 8 records, found 3"):
        finalize(m, EvaluationStore(a, EVAL))                    # interrupted run cannot be finalized
    _, second, _ = go(world, a)
    assert second.executed == 5 and second.skipped_done == 3 and second.complete
    _, third, _ = go(world, a)
    assert third.executed == 0 and third.skipped_done == 8        # idempotent restart: nothing re-executed
    go(world, b)
    assert episodes_json(m, a) == episodes_json(m, b)


def test_concurrency_does_not_change_results(world, tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    m, _, _ = go(world, a, max_workers=1)
    go(world, b, max_workers=3)
    assert episodes_json(m, a) == episodes_json(m, b)


def test_a_changed_manifest_cannot_reuse_or_merge_existing_results(world, tmp_path):
    go(world, tmp_path)
    cat, tasks, other, adapter = setup(world, seeds=(11, 13))
    with pytest.raises(ValueError, match="different evaluation manifests"):
        run_evaluation(other, tasks, catalog=cat, model_factory=lambda c: adapter, store=EvaluationStore(tmp_path, EVAL))


def test_drifted_tasks_are_refused_before_any_model_call(world, tmp_path):
    cat, tasks, manifest, adapter = setup(world)
    t0 = next(iter(tasks))
    tasks[t0] = tasks[t0].model_copy(update={"catalog_manifest_hash": "drift"})
    with pytest.raises(ValueError, match="hash mismatch"):
        run_evaluation(manifest, tasks, catalog=cat, model_factory=lambda c: adapter, store=EvaluationStore(tmp_path, EVAL))
    assert adapter.requests == []


def test_backend_outage_trips_the_breaker_quarantines_and_resumes_cleanly(world, tmp_path):
    manifest, out, _ = go(world, tmp_path, adapter=ScriptedModelAdapter({}))     # every call fails
    assert out.stopped_reason and out.status is RunStatus.INTERRUPTED and out.quarantined == 3 and out.unique_records == 0
    store = EvaluationStore(tmp_path, EVAL)
    assert len(store.load_episodes(manifest, quarantine=True)) == 3               # visible, not hidden
    _, resumed, _ = go(world, tmp_path)
    assert resumed.complete and resumed.unique_records == 8
    assert finalize(manifest, store)


def test_foreign_or_tampered_artifacts_are_rejected(world, tmp_path):
    manifest, _, _ = go(world, tmp_path)
    path = EvaluationStore(tmp_path, EVAL).episode_path(("base-qwen", manifest.tasks[0].id, 11))
    data = json.loads(path.read_text())
    data["manifest_hash"] = "0" * 64
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="different evaluation manifests"):
        EvaluationStore(tmp_path, EVAL).load_episodes(manifest)


def memory_world(world, tmp_path):
    """A pool of real (non-scripted-checkpoint) traces from the train/val reference tasks."""
    cat, _, reference = world
    sub = reference[:3]
    cs = contenders()
    m = build_manifest(evaluation_id="pool", tasks=sub, seeds=(5,), contenders=cs[:1], catalog_hash="c" * 64, versions=VERSIONS,
                       pass_k=1, created_at=NOW)
    run_evaluation(m, {t.id: t for t in sub}, catalog=cat, store=EvaluationStore(tmp_path, "pool"),
                   model_factory=lambda c: ScriptedModelAdapter(scripts_for(cat, sub, cs, "pool", (5,))))
    by = {t.id: t for t in sub}
    return tuple(trace_from_episode(a.episode, by[a.task_id], contender_genome(cs[0]))
                 for a in EvaluationStore(tmp_path, "pool").load_episodes(m).values())


def test_memory_contender_is_refused_without_a_pool_and_pool_is_audited(world, tmp_path):
    cat, tasks, _ = world
    cs = tuple(standard_contenders(model_id="Qwen/Qwen2.5-7B-Instruct", base_revision=REV, prompt_version="shopper-prompts-v1",
                                   endpoint="test:double"))
    _, tmap, manifest, adapter = setup(world, cs=cs)
    with pytest.raises(ValueError, match="non-empty audited memory pool"):
        run_evaluation(manifest, tmap, catalog=cat, model_factory=lambda c: adapter, store=EvaluationStore(tmp_path / "x", EVAL))
    assert adapter.requests == []
    pool = memory_world(world, tmp_path)
    assert pool
    leaky = pool[0].model_copy(update={"task_id": tasks[0].id})
    with pytest.raises(MemoryLeakage, match="evaluation task"):
        FrozenEvalMemory((*pool, leaky), tasks)
    protected_trace = pool[0].model_copy(update={"episode_id": "z", "split": "test"})
    with pytest.raises(MemoryLeakage):
        FrozenEvalMemory((protected_trace,), tasks)


def test_memory_contender_receives_retrieved_examples_and_base_does_not(world, tmp_path):
    cat, tasks, _ = world
    pool = memory_world(world, tmp_path)
    memory = FrozenEvalMemory(pool, tasks)
    cs = standard_contenders(model_id="Qwen/Qwen2.5-7B-Instruct", base_revision=REV, prompt_version="shopper-prompts-v1", endpoint="t")
    _, tmap, manifest, adapter = setup(world, cs=cs, seeds=(11,), memory_pool_hash=pool_hash(pool), memory_pool_size=len(pool))
    out = run_evaluation(manifest, tmap, catalog=cat, model_factory=lambda c: adapter, memory=memory,
                         store=EvaluationStore(tmp_path / "m", EVAL))
    assert out.complete and out.memory_pool_size == len(pool)
    seen = {}
    for r in adapter.requests:
        cid = r.request_id.split(":")[1]
        seen.setdefault(cid, False)
        seen[cid] |= any("retrieved_episode_id" in (m.content or "") for m in r.messages)
    assert seen == {"base-qwen": False, "base-qwen-memory": True}
    assert not any(t.episode_id.startswith(EVAL) for t in memory._inner.repo.traces)   # evaluation episodes never enter memory
