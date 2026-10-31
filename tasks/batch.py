"""Configurable seeded task batches over the complete frozen training snapshot."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from decimal import Decimal

from tasks.catalog import FrozenTrainingCatalog, complete_review_ids, require_frozen_training_catalog
from tasks.engine import SplitConfig, build_review_trap, build_task_from_products
from tasks.schemas import Difficulty, HardConstraints, ReviewSignal, TaskSpec


@dataclass(frozen=True)
class BatchConfig:
    size: int = 20
    feasible_percent: int = 75
    split: SplitConfig = SplitConfig()

    def __post_init__(self) -> None:
        if self.size < 10:
            raise ValueError("batch size must be at least 10 to guarantee the requested ratio band")
        if not 70 <= self.feasible_percent <= 80:
            raise ValueError("feasible_percent must be between 70 and 80")


@dataclass(frozen=True)
class ReviewTrapTemplate:
    category: str
    review_adjusted_best: str
    signals: tuple[ReviewSignal, ...]


@dataclass(frozen=True)
class TaskBatch:
    seed: int
    snapshot_id: str
    manifest_hash: str
    tasks: tuple[TaskSpec, ...]
    feasible_count: int
    impossible_count: int
    review_trap_count: int


def _feasible_count(config: BatchConfig) -> int:
    target = Decimal(config.size * config.feasible_percent) / Decimal(100)
    low = math.ceil(config.size * 0.70)
    high = math.floor(config.size * 0.80)
    return min(high, max(low, int(target.to_integral_value(rounding="ROUND_HALF_UP"))))


def _validate_template(catalog: FrozenTrainingCatalog, template: ReviewTrapTemplate) -> None:
    if not template.signals:
        raise ValueError("review-sensitive tasks require verified review signals, not ratings or rank")
    for signal in template.signals:
        if signal.product_id not in {p.id for p in catalog.enumerate_products(template.category)}:
            raise ValueError("review signal product is outside the enumerated category")
        if not set(signal.supporting_review_ids) <= complete_review_ids(catalog, signal.product_id):
            raise ValueError("review signal cites an absent or cross-product review ID")


def generate_batch(
    catalog: FrozenTrainingCatalog, *, seed: int, config: BatchConfig = BatchConfig(),
    review_templates: tuple[ReviewTrapTemplate, ...] = (),
) -> TaskBatch:
    catalog = require_frozen_training_catalog(catalog)
    categories = tuple(sorted(catalog.categories()))
    if not categories:
        raise ValueError("frozen training snapshot has no categories")
    enumerated = {category: tuple(sorted(catalog.enumerate_products(category), key=lambda p: p.id))
                  for category in categories}
    if any(not products for products in enumerated.values()):
        raise ValueError("every advertised category must enumerate at least one product")
    if any(product.variants for products in enumerated.values() for product in products):
        # Variants may exist in another real snapshot, but this Amazon contract explicitly has none.
        raise ValueError("this training batch contract excludes size/stock variant requirements")
    for template in review_templates:
        _validate_template(catalog, template)

    rng = random.Random(seed)
    feasible_count = _feasible_count(config)
    kinds = [True] * feasible_count + [False] * (config.size - feasible_count)
    rng.shuffle(kinds)
    templates = list(review_templates)
    tasks: list[TaskSpec] = []
    traps = 0
    for index, feasible in enumerate(kinds):
        template = templates.pop(0) if feasible and templates else None
        category = template.category if template else categories[rng.randrange(len(categories))]
        products = enumerated[category]
        if template:
            adjusted = next((p for p in products if p.id == template.review_adjusted_best), None)
            signaled = [p for p in products if p.id in {s.product_id for s in template.signals}]
            if adjusted is None or not signaled:
                raise ValueError("review template products are absent from enumeration")
            budget = max([adjusted.price, *(product.price for product in signaled)])
        elif feasible:
            budget = products[rng.randrange(len(products))].price
        else:
            minimum = min(product.price for product in products)
            budget = max(Decimal("0.01"), minimum - Decimal("0.01"))
            if budget >= minimum:
                raise ValueError("cannot construct a positive impossible budget for this category")
        task = build_task_from_products(
            task_id=f"batch-{seed}-{index:04d}", catalog_snapshot_id=catalog.snapshot_id,
            manifest_hash=catalog.manifest_hash, products=products,
            constraints=HardConstraints(category=category, max_total=budget, required_variant=None),
            seed=seed + index, split_config=config.split,
            review_signals=template.signals if template else (), difficulty=Difficulty.MEDIUM,
        )
        if template:
            task = build_review_trap(task, template.review_adjusted_best, catalog)
            traps += 1
        if not task.suitable_for_deterministic_training:
            raise ValueError("batch generation produced an uncheckable training task")
        tasks.append(task)
    actual_feasible = sum(not task.is_impossible for task in tasks)
    return TaskBatch(seed=seed, snapshot_id=catalog.snapshot_id,
                     manifest_hash=catalog.manifest_hash, tasks=tuple(tasks),
                     feasible_count=actual_feasible,
                     impossible_count=len(tasks) - actual_feasible, review_trap_count=traps)
