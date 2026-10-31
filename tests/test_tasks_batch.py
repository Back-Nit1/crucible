import datetime as dt
from decimal import Decimal

import pytest

from catalog.providers.base import Product
from tasks.batch import BatchConfig, DifficultyMix, generate_batch
from tasks.engine import LeakageGuard, SplitConfig
from tasks.schemas import TaskSplit


class FrozenFixture:
    def __init__(self) -> None:
        self.enumerations: list[str] = []
        self.products = {
            category: tuple(
                Product(
                    id=f"{category}-{index:03d}",
                    title=f"Test-only {category} item {index}",
                    category=category,
                    price=Decimal(index + 10),
                    source="synthetic-test-fixture",
                    as_of=dt.datetime(2023, 1, 1, tzinfo=dt.UTC),
                )
                for index in range(120)
            )
            for category in ("office", "audio")
        }

    def iter_products(self, category):
        self.enumerations.append(category)
        yield from self.products.get(category, ())

    def review_ids(self, product_id):
        return frozenset()

    def review_count(self, product_id):
        return 0

    def search(self, query, filters=None):
        raise AssertionError("ranked search must not generate task ground truth")

    def get_product(self, product_id):
        return next(
            (product for products in self.products.values() for product in products if product.id == product_id),
            None,
        )

    def get_reviews(self, product_id, focus=None, limit=10):
        return []


def config(**changes):
    values = {
        "size": 40,
        "feasible_percent": 75,
        "categories": ("office", "audio"),
        "difficulty": DifficultyMix(easy=25, medium=50, hard=25),
        "split": SplitConfig(train=60, validation=20, test=20),
    }
    values.update(changes)
    return BatchConfig(**values)


def make(seed=19, **changes):
    fixture = FrozenFixture()
    batch = generate_batch(
        catalog=fixture,
        snapshot_id="snapshot-real-shape-v1",
        catalog_manifest_hash="a" * 64,
        seed=seed,
        config=config(**changes),
    )
    return fixture, batch


def test_batch_hits_configured_ratio_and_difficulty_exactly():
    fixture, batch = make()
    assert batch.manifest.feasible_count == 30
    assert batch.manifest.impossible_count == 10
    assert batch.manifest.difficulty_counts == {"easy": 10, "medium": 20, "hard": 10}
    assert fixture.enumerations == ["office", "audio"]
    assert all(task.catalog_manifest_hash == "a" * 64 for task in batch.tasks)
    assert all(task.hard_constraints.required_variant is None for task in batch.tasks)
    assert all(not task.hard_constraints.attributes for task in batch.tasks)


def test_same_seed_has_same_tasks_and_manifest_different_seed_changes_hash():
    _, first = make(seed=31)
    _, again = make(seed=31)
    _, different = make(seed=32)
    assert first == again
    assert first.manifest.content_hash != different.manifest.content_hash


def test_product_partitions_prevent_protected_split_leakage():
    _, batch = make(seed=99)
    guard = LeakageGuard()
    for task in batch.tasks:
        guard.register(task)
    by_split = {
        split: {product for task in batch.tasks if task.split is split for product in task.feasible_set}
        for split in TaskSplit
    }
    protected = by_split[TaskSplit.TEST] | by_split[TaskSplit.HELD_OUT_CATEGORY]
    assert not protected & (by_split[TaskSplit.TRAIN] | by_split[TaskSplit.VALIDATION])


def test_held_out_category_is_isolated_and_manifested():
    _, batch = make(held_out_categories=frozenset({"audio"}))
    audio = [task for task in batch.tasks if task.hard_constraints.category == "audio"]
    assert audio and all(task.split is TaskSplit.HELD_OUT_CATEGORY for task in audio)
    assert batch.manifest.split_counts["held_out_category"] == len(audio)


def test_review_trap_target_fails_closed_without_verified_evidence():
    with pytest.raises(ValueError, match="verified review-trap evidence"):
        make(review_trap_percent=20)


def test_configuration_rejects_ratios_outside_required_band():
    with pytest.raises(ValueError):
        config(feasible_percent=69)
    with pytest.raises(ValueError):
        config(feasible_percent=81)
