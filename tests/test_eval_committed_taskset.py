"""Regression: the committed evaluation task set has no protected-split overlap (real frozen-snapshot ids, no review text)."""
import json
from pathlib import Path

from catalog.providers.elastic import load_manifest_hashes
from eval.leakage import audit, products_of
from eval.taskset import load_tasks
from tasks.schemas import TaskSplit

DIR = Path(__file__).resolve().parents[1] / "docs" / "evaluations" / "taskset-20261110"
META = json.loads((DIR / "taskset.json").read_text())
PROTECTED = load_tasks(DIR / "protected.jsonl", META["protected_hash"])
REFERENCE = load_tasks(DIR / "reference.jsonl", META["reference_hash"])
OFF = frozenset({"memory_eligibility", "training_source_leakage"})


def test_committed_taskset_passes_every_applicable_check_against_the_real_manifests():
    report = audit(protected=PROTECTED, reference=REFERENCE, category_manifests=load_manifest_hashes(), allow_not_run=OFF)
    assert report.passed, report.to_json()
    assert {n for n, c in report.checks.items() if c.status == "not_run"} == OFF
    assert report.content_hash == json.loads((DIR / "audit.json").read_text())["content_hash"]


def test_protected_products_never_appear_in_train_or_val_and_categories_are_isolated():
    protected_products = set().union(*(products_of(t) for t in PROTECTED))
    reference_products = set().union(*(products_of(t) for t in REFERENCE))
    assert not protected_products & reference_products
    test_p = set().union(*(products_of(t) for t in PROTECTED if t.split is TaskSplit.TEST))
    held_p = set().union(*(products_of(t) for t in PROTECTED if t.split is TaskSplit.HELD_OUT_CATEGORY))
    assert not test_p & held_p
    assert {t.hard_constraints.category for t in PROTECTED if t.split is TaskSplit.HELD_OUT_CATEGORY} == set(META["held_out_categories"])
    assert not {t.hard_constraints.category for t in REFERENCE} & set(META["held_out_categories"])


def test_taskset_is_large_enough_to_report_and_declares_its_exclusions():
    assert len(PROTECTED) >= 40 and any(t.is_impossible for t in PROTECTED) and any(t.is_review_trap for t in PROTECTED)
    excluded = json.loads((DIR / "exclusions.json").read_text())
    assert len(excluded) == META["excluded_duplicates"] and not {t.id for t in PROTECTED} & set(excluded)
