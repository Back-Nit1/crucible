"""Runner: identical matrix, atomic artifacts, resumption without duplicates, breaker, finalize refusal, memory rules.
The scripted model double reads answer keys: these tests check machinery, never model quality."""
import datetime as dt
import json
from decimal import Decimal

import pytest

from agents.actions import ConfirmAndPay, ProposePurchase
from agents.model import ScriptedModelAdapter
from eval.contenders import standard_contenders
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


def test_report_refuses_a_test_double_as_a_measurement_and_labels_it_otherwise(world, tmp_path):
    from eval.leakage import audit
    from eval.report import NotAMeasurement, build_report, to_markdown
    cat, tasks, reference = world
    manifest, _, _ = go(world, tmp_path)
    store = EvaluationStore(tmp_path, EVAL)
    rep = audit(protected=tasks, reference=reference, allow_not_run=frozenset({"memory_eligibility", "training_source_leakage", "catalog_manifest_match"}))
    tmap = {t.id: t for t in tasks}
    with pytest.raises(NotAMeasurement):
        build_report(manifest, store, tmap, audit=rep)
    report = build_report(manifest, store, tmap, audit=rep, allow_test_double=True)
    assert report["evidence_class"] == "test_double_not_a_measurement" and report["unique_records"] == report["expected_records"] == 8
    c = report["contenders"][0]
    assert c["webshop"]["status"] == "blocked_not_run" and c["webshop"]["mean_reward"] is None
    assert c["metrics"]["success_rate"]["denominator"] == "8" and c["latency"]["episodes"] == 8
    md = to_markdown(report)
    assert "test_double_not_a_measurement" in md and "MockPayments" in md and "snapshot prices" in md
    (tmp_path / "ev-test" / "episodes" / "base-qwen").joinpath(f"{manifest.tasks[0].id}__11.json").unlink()
    with pytest.raises(Incomplete):
        build_report(manifest, store, tmap, audit=rep, allow_test_double=True)


def _measured(world, tmp_path, double=False):
    from eval.leakage import audit
    from eval.report import build_report
    cat, tasks, reference = world
    manifest, _, _ = go(world, tmp_path)
    rep = audit(protected=tasks, reference=reference, category_manifests=HASHES, memory_traces=(), training_manifests=())
    store = EvaluationStore(tmp_path, EVAL)
    finalize(manifest, store)
    return build_report(manifest, store, {t.id: t for t in tasks}, audit=rep, allow_test_double=True), manifest


def test_publication_refuses_test_doubles_and_failed_audits_and_is_idempotent(world, tmp_path):
    from eval.publish import PublicationRefused, measured_docs
    report, manifest = _measured(world, tmp_path)
    with pytest.raises(PublicationRefused, match="measured model"):
        measured_docs(report)
    report["evidence_class"] = "measured_model"          # what a real Qwen run would carry
    docs = measured_docs(report)
    assert [i for i, _ in docs] == ["ev-test:base-qwen"]
    assert docs == measured_docs(report)                  # deterministic: no clock, same ids and bodies
    d = docs[0][1]
    assert d["seeds"] == [11, 12] and d["task_set_hash"] == manifest.task_set_hash and d["payment_backend"] == "mock"
    assert d["webshop"] == {"status": "blocked_not_run", "reason": "WebShop was not run for this contender",
                            "unmet_requirements": ["WebShop was not run for this contender"]}
    assert d["metrics"]["pass_at_k"] == d["metrics"]["pass_at_1"] and d["lineage"]["evaluation_manifest_hash"] == manifest.manifest_hash
    bad = {**report, "leakage_audit": {**report["leakage_audit"], "passed": False}}
    with pytest.raises(PublicationRefused, match="leakage"):
        measured_docs(bad)
    with pytest.raises(PublicationRefused, match="not complete"):
        measured_docs({**report, "unique_records": 1})


def test_double_publish_to_the_api_contract_creates_no_duplicates(world, tmp_path):
    from eval.publish import measured_docs, publish
    from tests.test_eval_publish import FakeEs
    report, _ = _measured(world, tmp_path)
    report["evidence_class"] = "measured_model"
    es = FakeEs()
    publish(es, "evaluations", measured_docs(report))
    first = dict(es.docs["evaluations"])
    publish(es, "evaluations", measured_docs(report))
    assert es.docs["evaluations"] == first and len(first) == 1


def test_trained_checkpoint_needs_a_validated_artifact_and_real_evaluations(world, tmp_path):
    import hashlib
    from eval.contenders import AdapterReference
    from eval.publish import trained_checkpoint_doc
    from eval.contenders import ContenderError
    from training.planning import LoRAPlan
    artifact = tmp_path / "a.safetensors"
    artifact.write_bytes(b"w")
    sha = hashlib.sha256(b"w").hexdigest()
    ref = AdapterReference(adapter_ref=str(artifact), adapter_sha256=sha, base_model="Qwen/Qwen2.5-7B-Instruct", base_revision=REV,
                           training_manifest_hash="b" * 64)
    plan = LoRAPlan.model_construct(base_model=ref.base_model, base_revision=REV, training_manifest_hash="b" * 64)
    with pytest.raises(ContenderError, match="no published evaluation"):
        trained_checkpoint_doc(ref, plan, [("x", {"adapter_sha256": None, "training_manifest_hash": None})], created_at=NOW)
    artifact.write_bytes(b"tampered")
    with pytest.raises(ContenderError, match="hash does not match"):
        trained_checkpoint_doc(ref, plan, [], created_at=NOW)


def test_base_sft_and_grpo_adapters_are_contenders_with_fitness_and_kill_rate_deltas(world, tmp_path):
    from eval.contenders import AdapterReference
    from eval.leakage import audit
    from eval.report import build_report
    cat, tasks, reference = world

    def ref(h):
        return AdapterReference(adapter_ref=f"modal-volume://crucible-qwen-adapters/runs/run-{h}/final@{h * 64}",
                                adapter_sha256=h * 64, base_model="Qwen/Qwen2.5-7B-Instruct", base_revision=REV,
                                training_manifest_hash="d" * 64)
    cs = tuple(c for c in standard_contenders(model_id="Qwen/Qwen2.5-7B-Instruct", base_revision=REV,
                                              prompt_version="shopper-prompts-v1", endpoint="test:double",
                                              adapters={"sft-a": ref("a"), "grpo-b": ref("b")}) if not c.memory_enabled)
    assert [c.request_checkpoint for c in cs] == [REV, "qwen-lora-" + "a" * 12, "qwen-lora-" + "b" * 12]  # no base fallback
    manifest, out, _ = go(world, tmp_path, cs=cs)
    rep = audit(protected=tasks, reference=reference, allow_not_run=frozenset({"memory_eligibility", "training_source_leakage",
                                                                                "catalog_manifest_match"}))
    report = build_report(manifest, EvaluationStore(tmp_path, EVAL), {t.id: t for t in tasks}, audit=rep, allow_test_double=True)
    by = {c["contender"]["id"]: c for c in report["contenders"]}
    assert list(by) == ["base-qwen", "sft-a", "grpo-b"] and by["base-qwen"]["vs_base"] is None
    for c in by.values():
        f, k = c["fitness"], c["kill_rate"]
        assert int(f["denominator"]) + f["excluded"] == 8 and k["denominator"] == "8" and f["value"] is not None
    for cid in ("sft-a", "grpo-b"):  # the scripted double plays every contender identically: deltas are exactly zero
        assert Decimal(by[cid]["vs_base"]["fitness_delta"]) == 0 and Decimal(by[cid]["vs_base"]["kill_rate_delta"]) == 0


def test_fitness_counts_killed_unscored_episodes_as_zero_and_excludes_other_unscored():
    from types import SimpleNamespace as E

    from eval.report import _fitness
    f = _fitness([E(score_components={"fitness": "0.8"}, killed=False), E(score_components={}, killed=True),
                  E(score_components={}, killed=False)])
    assert (f["numerator"], f["denominator"], f["excluded"], f["value"]) == ("0.8", "2", 1, "0.400000")


def test_an_episode_that_outgrew_the_context_is_a_result_not_a_backend_failure():
    from types import SimpleNamespace
    from eval.runner import is_backend_failure
    episode = lambda answer: SimpleNamespace(termination="model_failure", final_answer=answer)
    assert is_backend_failure(episode("model failure: InferenceError[timeout]"))
    assert not is_backend_failure(episode("model failure: InferenceError[input_too_long]"))
    assert not is_backend_failure(episode("model failure: MalformedModelOutput"))
