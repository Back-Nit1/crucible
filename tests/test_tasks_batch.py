from decimal import Decimal

import pytest

from tasks.batch import BatchConfig, ReviewTrapTemplate, generate_batch
from tasks.catalog import require_frozen_training_catalog
from tasks.schemas import ReviewSignal
from tests.fixtures.scoring import InMemoryCatalog


def snapshot_without_variants():
    catalog = InMemoryCatalog()
    catalog.products = {key: product.model_copy(update={"variants": {}})
                        for key, product in catalog.products.items()}
    return catalog


def test_seeded_batch_has_configured_feasible_impossible_ratio_and_no_variants():
    catalog = snapshot_without_variants()
    first = generate_batch(catalog, seed=91, config=BatchConfig(size=20, feasible_percent=75))
    second = generate_batch(catalog, seed=91, config=BatchConfig(size=20, feasible_percent=75))
    assert first == second
    assert (first.feasible_count, first.impossible_count) == (15, 5)
    assert all(task.hard_constraints.required_variant is None for task in first.tasks)
    assert all(task.suitable_for_deterministic_training for task in first.tasks)


def test_batch_rejects_nonfrozen_or_implicit_search_provider():
    class SearchOnly:
        pass
    with pytest.raises(TypeError, match="enumerate_products"):
        require_frozen_training_catalog(SearchOnly())


def test_review_trap_requires_complete_real_id_grounding():
    catalog = snapshot_without_variants()
    template = ReviewTrapTemplate(
        category="running-shoes", review_adjusted_best="shoe-b",
        signals=(ReviewSignal(concern="cushioning", product_id="shoe-a",
                              claim="supportive in the cited review fixture",
                              supporting_review_ids=("review-a-positive",)),),
    )
    batch = generate_batch(catalog, seed=2, config=BatchConfig(size=10),
                           review_templates=(template,))
    assert batch.review_trap_count == 1
    trap = next(task for task in batch.tasks if task.is_review_trap)
    assert trap.review_signals[0].supporting_review_ids == ("review-a-positive",)

    bad = ReviewTrapTemplate(category="running-shoes", review_adjusted_best="shoe-b",
        signals=(template.signals[0].model_copy(update={"supporting_review_ids": ("foreign",)}),))
    with pytest.raises(ValueError, match="absent or cross-product"):
        generate_batch(catalog, seed=2, config=BatchConfig(size=10), review_templates=(bad,))


def test_ratio_configuration_is_bounded():
    with pytest.raises(ValueError, match="between 70 and 80"):
        BatchConfig(feasible_percent=81)


def test_batch_rejects_snapshot_variants_instead_of_inventing_stock_checkability():
    with pytest.raises(ValueError, match="excludes size/stock"):
        generate_batch(InMemoryCatalog(), seed=1, config=BatchConfig(size=10))
