"""Deterministic hard-constraint gate (G in the scoring specification)."""

from catalog.providers.base import CatalogProvider
from scoring.schemas import (
    EpisodeTrace,
    GateResult,
    GateViolation,
    GateViolationCode,
    NoMatchOutcome,
)
from tasks.schemas import TaskSpec


def evaluate_gate(task: TaskSpec, trace: EpisodeTrace, catalog: CatalogProvider) -> GateResult:
    """Return G without judges, network calls, heuristics, or mutable state."""
    if trace.task_id != task.id or trace.catalog_snapshot_id != task.catalog_snapshot_id:
        raise ValueError("trace and task must reference the same task and catalog snapshot")

    violations: list[GateViolation] = []
    if isinstance(trace.outcome, NoMatchOutcome):
        if task.feasible_set:
            violations.append(
                GateViolation(
                    code=GateViolationCode.WRONG_REFUSAL,
                    product_id=trace.outcome.closest_product_id,
                    detail="task has at least one feasible product",
                )
            )
        if catalog.get_product(trace.outcome.closest_product_id) is None:
            violations.append(
                GateViolation(
                    code=GateViolationCode.INVALID_CLOSEST_PRODUCT,
                    product_id=trace.outcome.closest_product_id,
                    detail="closest product is absent from the catalog snapshot",
                )
            )
        return GateResult(value=int(not violations), violations=tuple(violations))

    for recommendation in trace.outcome.recommendations:
        product = catalog.get_product(recommendation.product_id)
        if product is None:
            violations.append(
                GateViolation(
                    code=GateViolationCode.PRODUCT_NOT_FOUND,
                    product_id=recommendation.product_id,
                    detail="recommended product is absent from the catalog snapshot",
                )
            )
            continue
        if product.category != task.hard_constraints.category:
            violations.append(
                GateViolation(
                    code=GateViolationCode.CATEGORY_MISMATCH,
                    product_id=product.id,
                    detail=f"expected category {task.hard_constraints.category}, got {product.category}",
                )
            )
        if not product.source or product.as_of is None:
            violations.append(
                GateViolation(code=GateViolationCode.MISSING_PROVENANCE, product_id=product.id,
                              detail="product lacks source or as-of provenance")
            )
        if recommendation.currency != task.hard_constraints.currency or product.currency != recommendation.currency:
            violations.append(
                GateViolation(code=GateViolationCode.CURRENCY_MISMATCH, product_id=product.id,
                              detail="recommendation, task, and catalog currency differ")
            )
        if recommendation.expected_total != product.price:
            violations.append(
                GateViolation(code=GateViolationCode.PRICE_MISMATCH, product_id=product.id,
                              detail=f"expected {recommendation.expected_total}, catalog lists {product.price}")
            )
        # A source with no inventory data (empty `variants`, e.g. Amazon Reviews 2023) has unverifiable stock: nothing
        # to check, and none is synthesised. Stock is enforced only where the source actually provides it.
        if product.variants and product.variants.get(recommendation.variant, 0) <= 0:
            violations.append(
                GateViolation(
                    code=GateViolationCode.OUT_OF_STOCK,
                    product_id=product.id,
                    detail=f"variant {recommendation.variant!r} is not in stock",
                )
            )
        if recommendation.expected_total > task.hard_constraints.max_total or product.price > task.hard_constraints.max_total:
            violations.append(
                GateViolation(
                    code=GateViolationCode.OVER_BUDGET,
                    product_id=product.id,
                    detail=(
                        f"expected total {recommendation.expected_total} exceeds cap "
                        f"{task.hard_constraints.max_total}"
                    ),
                )
            )
        if product.id not in task.feasible_set:
            violations.append(
                GateViolation(
                    code=GateViolationCode.NOT_IN_FEASIBLE_SET,
                    product_id=product.id,
                    detail="product does not satisfy the snapshot-derived hard constraints",
                )
            )
    return GateResult(value=int(not violations), violations=tuple(violations))
