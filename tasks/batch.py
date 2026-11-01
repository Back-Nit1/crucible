"""Configurable, seeded task batches over an explicitly enumerable snapshot."""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Mapping

from catalog.providers.base import FrozenCatalogProvider, Product
from pydantic import Field, model_validator

from tasks.engine import LeakageGuard, SplitConfig, build_review_trap, build_task_from_products
from tasks.schemas import ContractModel, Difficulty, HardConstraints, ReviewSignal, TaskSpec, TaskSplit

_CENT = Decimal("0.01")


class DifficultyMix(ContractModel):
    easy: int = Field(default=30, ge=0, le=100)
    medium: int = Field(default=50, ge=0, le=100)
    hard: int = Field(default=20, ge=0, le=100)

    @model_validator(mode="after")
    def totals_one_hundred(self) -> "DifficultyMix":
        if self.easy + self.medium + self.hard != 100:
            raise ValueError("difficulty percentages must total 100")
        return self


class BatchConfig(ContractModel):
    size: int = Field(ge=10)
    feasible_percent: int = Field(default=75, ge=70, le=80)
    review_trap_percent: int = Field(default=0, ge=0, le=100)
    categories: tuple[str, ...] = Field(min_length=1)
    held_out_categories: frozenset[str] = frozenset()
    split: SplitConfig = SplitConfig()
    difficulty: DifficultyMix = Field(default_factory=DifficultyMix)

    @model_validator(mode="after")
    def validate_categories(self) -> "BatchConfig":
        if len(set(self.categories)) != len(self.categories):
            raise ValueError("categories must be unique")
        if not self.held_out_categories <= set(self.categories):
            raise ValueError("held-out categories must be included in categories")
        return self


class ReviewTrapPlan(ContractModel):
    """A separately verified signal and its grounded review-adjusted choice."""

    signal: ReviewSignal
    review_adjusted_best: str = Field(min_length=1)


class BatchManifest(ContractModel):
    schema_version: str = "1.0"
    snapshot_id: str = Field(min_length=1)
    catalog_manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")  # digest of category_manifest_hashes
    category_manifest_hashes: dict[str, str]
    seed: int = Field(ge=0)
    config: dict[str, object]
    task_ids: tuple[str, ...]
    task_hashes: tuple[str, ...]
    feasible_count: int
    impossible_count: int
    review_trap_count: int
    split_counts: dict[str, int]
    difficulty_counts: dict[str, int]
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class TaskBatch:
    tasks: tuple[TaskSpec, ...]
    manifest: BatchManifest


def _hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _exact_labels(size: int, percentages: Mapping[str, int]) -> list[str]:
    raw = {name: Decimal(size * percent) / Decimal(100) for name, percent in percentages.items()}
    counts = {name: int(value) for name, value in raw.items()}
    remainder = size - sum(counts.values())
    order = sorted(raw, key=lambda name: (-(raw[name] - counts[name]), name))
    for name in order[:remainder]:
        counts[name] += 1
    return [name for name in sorted(counts) for _ in range(counts[name])]


def _product_split(product: Product, category: str, seed: int, config: BatchConfig) -> TaskSplit:
    if category in config.held_out_categories:
        return TaskSplit.HELD_OUT_CATEGORY
    digest = hashlib.sha256(f"{seed}|product|{category}|{product.id}".encode()).digest()
    bucket = int.from_bytes(digest[:8], "big") % 100
    if bucket < config.split.train:
        return TaskSplit.TRAIN
    if bucket < config.split.train + config.split.validation:
        return TaskSplit.VALIDATION
    return TaskSplit.TEST


def _task_split(task_id: str, category: str, seed: int, config: BatchConfig) -> TaskSplit:
    if category in config.held_out_categories:
        return TaskSplit.HELD_OUT_CATEGORY
    digest = hashlib.sha256(f"{seed}|task|{task_id}|{category}".encode()).digest()
    bucket = int.from_bytes(digest[:8], "big") % 100
    if bucket < config.split.train:
        return TaskSplit.TRAIN
    if bucket < config.split.train + config.split.validation:
        return TaskSplit.VALIDATION
    return TaskSplit.TEST


def _eligible_trap(
    plans: Iterable[ReviewTrapPlan], products: tuple[Product, ...], catalog: FrozenCatalogProvider
) -> ReviewTrapPlan | None:
    product_ids = {product.id for product in products}
    for plan in plans:
        signal = plan.signal
        if signal.product_id not in product_ids or plan.review_adjusted_best not in product_ids:
            continue
        if set(signal.supporting_review_ids) <= catalog.get_review_ids(signal.product_id).ids:
            return plan
    return None


def generate_batch(
    *,
    catalog: FrozenCatalogProvider,
    snapshot_id: str,
    manifests: Mapping[str, str],
    seed: int,
    config: BatchConfig,
    review_trap_plans: Mapping[str, tuple[ReviewTrapPlan, ...]] | None = None,
) -> TaskBatch:
    """Generate a reproducible, product-disjoint batch from full enumeration.

    The only discovery call is ``iter_products``. Hard constraints are category
    and price, so missing inventory or size data is never guessed or converted
    into an impossible label.
    """
    missing = sorted(set(config.categories) - set(manifests))
    if missing:
        raise ValueError(f"no manifest hash for categories: {missing}")
    category_hashes = {category: manifests[category] for category in sorted(config.categories)}
    catalog_manifest_hash = _hash(category_hashes)
    rng = random.Random(seed)
    enumerated = {
        category: tuple(sorted(catalog.iter_products(category, manifests[category]), key=lambda product: product.id))
        for category in config.categories
    }
    empty = sorted(category for category, products in enumerated.items() if not products)
    if empty:
        raise ValueError(f"cannot generate from empty categories: {empty}")

    feasible_count = round(config.size * config.feasible_percent / 100)
    feasibility = [True] * feasible_count + [False] * (config.size - feasible_count)
    difficulties = _exact_labels(
        config.size,
        {"easy": config.difficulty.easy, "medium": config.difficulty.medium, "hard": config.difficulty.hard},
    )
    rng.shuffle(feasibility)
    rng.shuffle(difficulties)
    categories = [config.categories[index % len(config.categories)] for index in range(config.size)]
    rng.shuffle(categories)

    requested_traps = round(feasible_count * config.review_trap_percent / 100)
    trap_slots = set(rng.sample([i for i, value in enumerate(feasibility) if value], requested_traps))
    plans = review_trap_plans or {}
    guard = LeakageGuard()
    tasks: list[TaskSpec] = []
    traps_built = 0
    for index, (category, is_feasible, difficulty_name) in enumerate(
        zip(categories, feasibility, difficulties, strict=True)
    ):
        task_id = f"batch-{seed}-{index:04d}"
        split = _task_split(task_id, category, seed, config)
        pool = tuple(
            product for product in enumerated[category]
            if _product_split(product, category, seed, config) is split
        )
        if not pool:
            raise ValueError(f"split {split} has no enumerated products in {category}")
        trap_plan = _eligible_trap(plans.get(category, ()), pool, catalog) if index in trap_slots else None
        if index in trap_slots and trap_plan is None:
            raise ValueError(f"not enough verified review-trap evidence for {category}/{split}")
        ordered = sorted(pool, key=lambda product: (product.price, product.id))
        if trap_plan is not None:
            ids = {trap_plan.signal.product_id, trap_plan.review_adjusted_best}
            cap = max(product.price for product in pool if product.id in ids)
            signals = (trap_plan.signal,)
        elif is_feasible:
            cap = ordered[rng.randrange(len(ordered))].price
            signals = ()
        else:
            cap = max(_CENT, ordered[0].price - _CENT)
            signals = ()
        task_seed = rng.randrange(2**31)
        task = build_task_from_products(
            task_id=task_id,
            catalog_snapshot_id=snapshot_id,
            products=pool,
            constraints=HardConstraints(category=category, max_total=cap),
            seed=task_seed,
            split_config=config.split,
            review_signals=signals,
            difficulty=Difficulty(difficulty_name),
            manifest_hash=manifests[category],
            split=split,
        )
        if is_feasible != (not task.is_impossible):
            raise RuntimeError("generated feasibility does not match configured slot")
        if trap_plan is not None:
            task = build_review_trap(task, trap_plan.review_adjusted_best, catalog)
            traps_built += 1
        guard.register(task)
        tasks.append(task)

    task_hashes = tuple(_hash(task.model_dump(mode="json")) for task in tasks)
    payload = {
        "schema_version": "1.0",
        "snapshot_id": snapshot_id,
        "catalog_manifest_hash": catalog_manifest_hash,
        "category_manifest_hashes": category_hashes,
        "seed": seed,
        "config": config.model_dump(mode="json"),
        "task_ids": [task.id for task in tasks],
        "task_hashes": task_hashes,
    }
    split_counts = {split.value: sum(task.split is split for task in tasks) for split in TaskSplit}
    difficulty_counts = {
        difficulty.value: sum(task.difficulty is difficulty for task in tasks) for difficulty in Difficulty
    }
    manifest = BatchManifest(
        **payload,
        feasible_count=sum(not task.is_impossible for task in tasks),
        impossible_count=sum(task.is_impossible for task in tasks),
        review_trap_count=traps_built,
        split_counts=split_counts,
        difficulty_counts=difficulty_counts,
        content_hash=_hash(payload),
    )
    return TaskBatch(tuple(tasks), manifest)
