from decimal import Decimal
import datetime as dt

from tasks.engine import (
    LeakageGuard,
    SplitConfig,
    build_review_trap,
    build_task,
    compute_feasible_set,
    render_request,
)
from tasks.schemas import ConstraintEvidence, HardConstraints, TaskSplit
from tasks.review_signals import LexicalRule, extract_lexical_signals
from tasks.schemas import ReviewPolarity
from tests.fixtures.scoring import InMemoryCatalog


def constraints(**changes):
    values = {"category": "running-shoes", "max_total": Decimal("95.00"), "required_variant": "12"}
    values.update(changes)
    return HardConstraints(**values)


def test_feasible_set_and_task_generation_are_seeded_and_stable():
    catalog = InMemoryCatalog()
    result = compute_feasible_set(catalog.search("", {"category": "running-shoes"}), constraints())
    assert result.product_ids == ("shoe-a",)
    first = build_task(task_id="generated-1", catalog_snapshot_id="snap-1", catalog=catalog,
                       constraints=constraints(), seed=42)
    second = build_task(task_id="generated-1", catalog_snapshot_id="snap-1", catalog=catalog,
                        constraints=constraints(), seed=42)
    assert first == second
    assert first.catalog_manifest_hash == second.catalog_manifest_hash
    assert len(first.catalog_manifest_hash) == 64


def test_uncheckable_required_variant_is_unsuitable_not_guessed():
    hard = constraints(variant_evidence=ConstraintEvidence(
        checkable=False, provenance="Amazon 2023 metadata has no inventory"))
    result = compute_feasible_set(InMemoryCatalog().products.values(), hard)
    assert result.product_ids == ()
    assert not result.suitable_for_training
    task = build_task(task_id="uncheckable", catalog_snapshot_id="snap", catalog=InMemoryCatalog(),
                      constraints=hard, seed=4)
    assert not task.is_impossible and not task.suitable_for_deterministic_training


def test_seeded_renderer_and_split_are_reproducible():
    assert render_request(constraints(), (), (), 9) == render_request(constraints(), (), (), 9)
    config = SplitConfig(held_out_categories=frozenset({"running-shoes"}))
    task = build_task(task_id="held-1", catalog_snapshot_id="snap-1", catalog=InMemoryCatalog(),
                      constraints=constraints(), seed=9, split_config=config)
    assert task.split is TaskSplit.HELD_OUT_CATEGORY and task.held_out_category


def test_review_traps_require_real_product_scoped_review_ids():
    catalog = InMemoryCatalog()
    signal = extract_lexical_signals(
        catalog,
        "shoe-a",
        (LexicalRule(
            concern="cushioning",
            phrases=("cushioning remained supportive",),
            persona_relevance="runner seeking support",
            polarity=ReviewPolarity.POSITIVE,
        ),),
        extracted_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
    ).signals[0]
    task = build_task(task_id="trap-1", catalog_snapshot_id="snap-1", catalog=catalog,
                      constraints=constraints(max_total=Decimal("100.00")), seed=2,
                      review_signals=(signal,))
    trapped = build_review_trap(task, "shoe-b", catalog)
    assert trapped.is_review_trap and trapped.review_adjusted_best == "shoe-b"


def test_leakage_guard_protects_test_products():
    catalog = InMemoryCatalog()
    one = build_task(task_id="one", catalog_snapshot_id="snap", catalog=catalog,
                     constraints=constraints(), seed=1)
    two = one.model_copy(update={"id": "two", "split": TaskSplit.TEST})
    guard = LeakageGuard()
    guard.register(one)
    if one.split is not TaskSplit.TEST:
        import pytest
        with pytest.raises(ValueError, match="leakage"):
            guard.register(two)
