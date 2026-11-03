"""Protected-split leakage: detector sensitivity, root cause of the old overlaps, and the clean evaluation set."""
import datetime as dt

import pytest

from eval.leakage import audit
from eval.taskset import build_eval_taskset, dedupe_protected, load_tasks, partition, write_tasks
from memory import TraceRecord
from tasks.engine import SplitConfig
from tasks.schemas import TaskSplit
from tests.fixtures.eval_catalog import HASHES, BigSynthetic
from world.taskgen import generate_tasks


@pytest.fixture(scope="module")
def catalog():
    return BigSynthetic()


@pytest.fixture(scope="module")
def batch(catalog):
    return build_eval_taskset(catalog, HASHES, seed=7, size=60, held_out_categories=frozenset({"gizmos"}))


def test_world_taskgen_whole_category_tasks_leak_across_splits(catalog):
    """Root cause: same category, different budgets -> shared cheap products across train and test."""
    tasks = generate_tasks(catalog, HASHES, seed=3, count=40, review_traps=0, split_config=SplitConfig(40, 10, 50))
    protected, reference = partition(tasks)
    assert protected and reference
    report = audit(protected=protected, reference=reference, allow_not_run=frozenset({"memory_eligibility", "training_source_leakage", "catalog_manifest_match"}))
    assert report.checks["product_overlap"].status == "fail" and not report.passed


def test_product_disjoint_batch_has_no_protected_overlap(batch):
    protected, reference = partition(batch.tasks)
    assert audit(protected=protected, reference=reference).checks["duplicate_messages"].status == "fail"  # templated text collides
    protected, excluded = dedupe_protected(protected, reference)
    assert excluded and all(r.startswith("duplicate request text of") for r in excluded.values())
    assert {t.split for t in protected} == {TaskSplit.TEST, TaskSplit.HELD_OUT_CATEGORY} and reference
    report = audit(protected=protected, reference=reference, category_manifests=HASHES, memory_traces=(), training_manifests=(),
                   allow_not_run=frozenset())
    assert report.passed, report.to_json()
    assert all(c.status == "pass" for c in report.checks.values())
    assert report.content_hash == audit(protected=protected, reference=reference, category_manifests=HASHES, memory_traces=(),
                                        training_manifests=()).content_hash


def test_task_id_message_review_and_category_collisions_are_detected(batch):
    protected, reference = partition(batch.tasks)
    t, r = protected[0], reference[0]
    clone = r.model_copy(update={"id": t.id})
    assert audit(protected=protected, reference=(clone, *reference)).checks["task_id_collisions"].status == "fail"
    same_msg = r.model_copy(update={"raw_message": t.raw_message.upper() + "!!"})
    assert audit(protected=protected, reference=(same_msg,)).checks["duplicate_messages"].status == "fail"
    held = next(x for x in protected if x.split is TaskSplit.HELD_OUT_CATEGORY)
    same_cat = r.model_copy(update={"hard_constraints": r.hard_constraints.model_copy(update={"category": held.hard_constraints.category})})
    assert audit(protected=protected, reference=(same_cat,)).checks["category_overlap"].status == "fail"
    trap = next((x for x in protected if x.review_signals), None)
    if trap:
        r2 = r.model_copy(update={"review_signals": trap.review_signals})
        assert audit(protected=protected, reference=(r2,)).checks["review_overlap"].status == "fail"


def trace(**kw):
    base = dict(episode_id="e", task_id="train-1", agent_id="a", split="train", task_text="something else", killed=False, fitness=1.0,
                scored=True, genome={"model_checkpoint": "qwen"})
    return TraceRecord(**{**base, **kw})


def test_memory_pool_leakage_is_detected(batch):
    protected, reference = partition(batch.tasks)
    t = protected[0]
    p = sorted(t.feasible_set or [t.closest_product_id])[0]
    bad = (trace(episode_id="a", split="test"), trace(episode_id="b", task_id=t.id), trace(episode_id="c", task_text=t.raw_message),
           trace(episode_id="d", genome={"model_checkpoint": "scripted-v1"}), trace(episode_id="e", final_answer=f"Recommend {p} now"))
    res = audit(protected=protected, reference=reference, memory_traces=bad).checks["memory_eligibility"]
    assert res.status == "fail" and res.violations == 5
    assert audit(protected=protected, reference=reference, memory_traces=(trace(),)).checks["memory_eligibility"].status == "pass"
    assert audit(protected=protected, reference=reference).checks["memory_eligibility"].status == "not_run"


def test_unrun_checks_block_a_passing_audit(batch):
    protected, reference = partition(batch.tasks)
    assert not audit(protected=protected, reference=reference).passed


def test_training_manifest_source_leakage(batch):
    from training.curation import TrainingManifest
    protected, reference = partition(batch.tasks)

    def manifest(eps, splits):
        return TrainingManifest(catalog_hash="c", task_version="v", rule_version="r", model_version="m", source_episode_ids=eps,
                                splits=(TaskSplit.TRAIN,), source_task_splits=splits, deduplication_hash="d" * 64,
                                created_at=dt.datetime(2026, 11, 1, tzinfo=dt.UTC), content_hash="e" * 64)
    ok = manifest(("g:a:" + reference[0].id,), {"g:a:" + reference[0].id: TaskSplit.TRAIN})
    leak = manifest(("g:a:" + protected[0].id,), {"g:a:" + protected[0].id: TaskSplit.TEST})
    assert audit(protected=protected, reference=reference, training_manifests=(ok,)).checks["training_source_leakage"].status == "pass"
    assert audit(protected=protected, reference=reference, training_manifests=(leak,)).checks["training_source_leakage"].violations == 2


def test_catalog_manifest_mismatch_is_detected(batch):
    protected, reference = partition(batch.tasks)
    assert audit(protected=protected, reference=reference, category_manifests={**HASHES, "widgets": "0" * 64}).checks[
        "catalog_manifest_match"].status == "fail"


def test_taskset_round_trip_and_tamper_detection(batch, tmp_path):
    protected, _ = partition(batch.tasks)
    h = write_tasks(tmp_path / "t.jsonl", protected)
    assert load_tasks(tmp_path / "t.jsonl", h) == protected
    (tmp_path / "t.jsonl").write_text((tmp_path / "t.jsonl").read_text().replace("batch-7", "batch-8", 1))
    with pytest.raises(ValueError, match="hash differs"):
        load_tasks(tmp_path / "t.jsonl", h)
