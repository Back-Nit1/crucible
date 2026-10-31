"""Deterministic task construction over an injected frozen catalog."""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

from catalog.providers.base import CatalogProvider, Product, SnapshotCatalog
from tasks.schemas import (
    Ambiguity,
    ConstraintOperator,
    Difficulty,
    HardConstraints,
    ImpliedNeed,
    ReviewSignal,
    SignalVerification,
    TaskSpec,
    TaskSplit,
)


@dataclass(frozen=True)
class FeasibilityResult:
    product_ids: tuple[str, ...]
    suitable_for_training: bool
    unsuitable_reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class SplitConfig:
    train: int = 70
    validation: int = 15
    test: int = 15
    held_out_categories: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if min(self.train, self.validation, self.test) < 0:
            raise ValueError("split weights cannot be negative")
        if self.train + self.validation + self.test != 100:
            raise ValueError("split weights must total 100")


def _matches(value: object, operator: ConstraintOperator, expected: tuple[object, ...]) -> bool:
    if operator is ConstraintOperator.EQ:
        return value == expected[0]
    if operator is ConstraintOperator.IN:
        return value in expected
    try:
        if operator is ConstraintOperator.GTE:
            return value >= expected[0]  # type: ignore[operator]
        return value <= expected[0]  # type: ignore[operator]
    except TypeError:
        return False


def compute_feasible_set(products: Iterable[Product], constraints: HardConstraints) -> FeasibilityResult:
    """Filter only checkable facts; reject a task if any required fact is unverifiable."""
    unchecked: list[str] = []
    if not constraints.category_evidence.checkable:
        unchecked.append("category is not catalog-checkable")
    if not constraints.price_evidence.checkable:
        unchecked.append("price is not catalog-checkable")
    if constraints.required_variant and not constraints.variant_evidence.checkable:
        unchecked.append("required variant availability is not catalog-checkable")
    unchecked.extend(
        f"attribute {item.attribute!r} is not catalog-checkable"
        for item in constraints.attributes
        if not item.evidence.checkable
    )
    if unchecked:
        return FeasibilityResult((), False, tuple(unchecked))

    feasible: list[str] = []
    for product in products:
        if product.category != constraints.category or product.price > constraints.max_total:
            continue
        if constraints.required_variant is not None and product.variants.get(
            constraints.required_variant, 0
        ) <= 0:
            continue
        if any(
            item.attribute not in product.attributes
            or not _matches(product.attributes[item.attribute], item.operator, item.values)
            for item in constraints.attributes
        ):
            continue
        feasible.append(product.id)
    return FeasibilityResult(tuple(sorted(set(feasible))), True)


def implied_needs_fit(product: Product, needs: tuple[ImpliedNeed, ...]) -> Decimal:
    mapped = [need for need in needs if need.attribute and need.acceptable_values]
    if not mapped:
        return Decimal("0.5")
    total = sum((Decimal(str(need.weight)) for need in mapped), Decimal(0))
    matched = sum(
        (
            Decimal(str(need.weight))
            for need in mapped
            if product.attributes.get(need.attribute) in need.acceptable_values
        ),
        Decimal(0),
    )
    return matched / total


def value_score(product: Product, max_total: Decimal, needs: tuple[ImpliedNeed, ...]) -> Decimal:
    """Explicit formula: 70% price headroom plus 30% mapped implied-needs fit."""
    price_headroom = max(Decimal(0), (max_total - product.price) / max_total)
    return Decimal("0.7") * price_headroom + Decimal("0.3") * implied_needs_fit(product, needs)


def select_best_value(
    products: Iterable[Product], feasible_ids: tuple[str, ...], max_total: Decimal,
    needs: tuple[ImpliedNeed, ...] = (),
) -> str | None:
    candidates = [product for product in products if product.id in feasible_ids]
    if not candidates:
        return None
    return min(candidates, key=lambda p: (-value_score(p, max_total, needs), p.id)).id


def select_closest(products: Iterable[Product], constraints: HardConstraints) -> str | None:
    products = tuple(products)
    if not products:
        return None
    def distance(product: Product) -> tuple[int, Decimal, str]:
        misses = int(product.category != constraints.category)
        misses += int(
            constraints.required_variant is not None
            and product.variants.get(constraints.required_variant, 0) <= 0
        )
        misses += sum(
            item.attribute not in product.attributes
            or not _matches(product.attributes.get(item.attribute), item.operator, item.values)
            for item in constraints.attributes
        )
        over = max(Decimal(0), product.price - constraints.max_total)
        return misses, over, product.id
    return min(products, key=distance).id


def assign_split(key: str, category: str, seed: int, config: SplitConfig) -> TaskSplit:
    if category in config.held_out_categories:
        return TaskSplit.HELD_OUT_CATEGORY
    digest = hashlib.sha256(f"{seed}|{key}|{category}".encode()).digest()
    bucket = int.from_bytes(digest[:8], "big") % 100
    if bucket < config.train:
        return TaskSplit.TRAIN
    if bucket < config.train + config.validation:
        return TaskSplit.VALIDATION
    return TaskSplit.TEST


def catalog_manifest_hash(products: Iterable[Product]) -> str:
    payload = [
        product.model_dump(mode="json")
        for product in sorted(products, key=lambda product: product.id)
    ]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def render_request(
    constraints: HardConstraints, needs: tuple[ImpliedNeed, ...], ambiguities: tuple[Ambiguity, ...], seed: int
) -> str:
    """Render a reproducible messy single-message request without inventing product facts."""
    rng = random.Random(seed)
    openers = ("hey, im after", "Hi! need", "ok so I need")
    budget = f"under ${constraints.max_total} all in"
    variant = f", maybe size {constraints.required_variant} or smth" if constraints.required_variant else ""
    need_text = ", ".join(need.concern.replace("-", " ") for need in needs)
    context = f". im worried about {need_text}" if need_text else ""
    ambiguity = f". by that I mean {ambiguities[0].source_text}" if ambiguities else ""
    unit_noise = " for about 10k-ish" if rng.randrange(3) == 0 else ""
    return f"{rng.choice(openers)} {constraints.category.replace('-', ' ')} {budget}{variant}{unit_noise}{context}{ambiguity}. thx"


def build_task(
    *, task_id: str, catalog_snapshot_id: str, catalog: CatalogProvider,
    constraints: HardConstraints, seed: int, split_config: SplitConfig = SplitConfig(),
    implied_needs: tuple[ImpliedNeed, ...] = (), ambiguities: tuple[Ambiguity, ...] = (),
    review_signals: tuple[ReviewSignal, ...] = (), difficulty: Difficulty = Difficulty.MEDIUM,
) -> TaskSpec:
    products = tuple(catalog.search("", {"category": constraints.category}))
    return build_task_from_products(
        task_id=task_id,
        catalog_snapshot_id=catalog_snapshot_id,
        products=products,
        constraints=constraints,
        seed=seed,
        split_config=split_config,
        implied_needs=implied_needs,
        ambiguities=ambiguities,
        review_signals=review_signals,
        difficulty=difficulty,
    )


def build_task_from_products(
    *,
    task_id: str,
    catalog_snapshot_id: str,
    products: Iterable[Product],
    constraints: HardConstraints,
    seed: int,
    split_config: SplitConfig = SplitConfig(),
    implied_needs: tuple[ImpliedNeed, ...] = (),
    ambiguities: tuple[Ambiguity, ...] = (),
    review_signals: tuple[ReviewSignal, ...] = (),
    difficulty: Difficulty = Difficulty.MEDIUM,
    manifest_hash: str | None = None,
    split: TaskSplit | None = None,
) -> TaskSpec:
    """Build ground truth from an explicit, already-enumerated projection.

    Production batches use this path so ranked search can never be mistaken for
    complete enumeration. A split-specific projection permits product-disjoint
    train, validation, test, and held-out tasks.
    """
    products = tuple(products)
    feasibility = compute_feasible_set(products, constraints)
    feasible = feasibility.product_ids
    best = select_best_value(products, feasible, constraints.max_total, implied_needs)
    assigned_split = split or assign_split(task_id, constraints.category, seed, split_config)
    closest = select_closest(products, constraints) if not feasible and feasibility.suitable_for_training else None
    return TaskSpec(
        id=task_id,
        catalog_snapshot_id=catalog_snapshot_id,
        catalog_manifest_hash=manifest_hash or catalog_manifest_hash(products),
        raw_message=render_request(constraints, implied_needs, ambiguities, seed),
        hard_constraints=constraints,
        implied_needs=implied_needs,
        ambiguities=ambiguities,
        feasible_set=feasible,
        best_value_reference=best,
        difficulty=difficulty,
        is_impossible=feasibility.suitable_for_training and not feasible,
        closest_product_id=closest,
        review_signals=review_signals,
        split=assigned_split,
        held_out_category=assigned_split is TaskSplit.HELD_OUT_CATEGORY,
        seed=seed,
        suitable_for_deterministic_training=feasibility.suitable_for_training,
        unsuitable_reasons=feasibility.unsuitable_reasons,
    )


def build_review_trap(task: TaskSpec, review_adjusted_best: str, catalog: SnapshotCatalog) -> TaskSpec:
    """Create a trap only from product-scoped, existing review evidence."""
    if review_adjusted_best not in task.feasible_set or review_adjusted_best == task.best_value_reference:
        raise ValueError("review-adjusted best must be a distinct feasible product")
    if not task.review_signals:
        raise ValueError("ratings alone cannot create a review trap")
    for signal in task.review_signals:
        if signal.verification_status not in {
            SignalVerification.AUTOMATED,
            SignalVerification.HUMAN_APPROVED,
        }:
            raise ValueError("review traps require verified signals")
        existing = catalog.review_ids(signal.product_id)
        if not set(signal.supporting_review_ids) <= existing:
            raise ValueError("review signal cites missing or misattributed review IDs")
    return task.model_copy(update={"is_review_trap": True, "review_adjusted_best": review_adjusted_best})


class LeakageGuard:
    """Reject duplicate task IDs and product overlap across protected split families."""

    def __init__(self) -> None:
        self._task_ids: set[str] = set()
        self._products: dict[TaskSplit, set[str]] = {}

    def register(self, task: TaskSpec) -> None:
        if task.id in self._task_ids:
            raise ValueError(f"duplicate task id {task.id}")
        products = set(task.feasible_set)
        products.update(signal.product_id for signal in task.review_signals)
        products.update(
            product_id
            for product_id in (task.closest_product_id, task.best_value_reference, task.review_adjusted_best)
            if product_id is not None
        )
        protected = {TaskSplit.TEST, TaskSplit.HELD_OUT_CATEGORY}
        for split, seen in self._products.items():
            if task.split != split and (task.split in protected or split in protected) and products & seen:
                raise ValueError("product leakage across protected split boundary")
        self._task_ids.add(task.id)
        self._products.setdefault(task.split, set()).update(products)
