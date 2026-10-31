from decimal import Decimal

from scoring.gate import evaluate_gate
from scoring.schemas import (
    EpisodeTrace,
    GateViolationCode,
    NoMatchOutcome,
    Recommendation,
    RecommendationOutcome,
)
from tests.fixtures.scoring import InMemoryCatalog, feasible_task, grounded_trace


def with_outcome(trace, outcome):
    return EpisodeTrace(**{**trace.model_dump(), "outcome": outcome})


def test_gate_passes_for_snapshot_grounded_in_budget_pick():
    result = evaluate_gate(feasible_task(), grounded_trace(), InMemoryCatalog())
    assert result.value == 1
    assert result.violations == ()


def test_gate_rejects_unknown_product():
    trace = with_outcome(
        grounded_trace(),
        RecommendationOutcome(
            recommendations=(
                Recommendation(
                    product_id="ghost", variant="12", expected_total=Decimal("80.00")
                ),
            )
        ),
    )
    result = evaluate_gate(feasible_task(), trace, InMemoryCatalog())
    assert result.value == 0
    assert result.violations[0].code is GateViolationCode.PRODUCT_NOT_FOUND


def test_gate_rejects_wrong_refusal():
    trace = with_outcome(
        grounded_trace(),
        NoMatchOutcome(
            reason="Nothing fits.",
            closest_product_id="shoe-a",
            why_it_misses="Claimed it was too expensive.",
        ),
    )
    result = evaluate_gate(feasible_task(), trace, InMemoryCatalog())
    assert result.value == 0
    assert result.violations[0].code is GateViolationCode.WRONG_REFUSAL


def test_gate_rejects_budget_and_stock_violations():
    trace = with_outcome(
        grounded_trace(),
        RecommendationOutcome(
            recommendations=(
                Recommendation(
                    product_id="shoe-a", variant="13", expected_total=Decimal("101.00")
                ),
            )
        ),
    )
    codes = {v.code for v in evaluate_gate(feasible_task(), trace, InMemoryCatalog()).violations}
    assert codes == {
        GateViolationCode.OUT_OF_STOCK,
        GateViolationCode.OVER_BUDGET,
        GateViolationCode.PRICE_MISMATCH,
    }


def test_snapshot_without_stock_data_does_not_fail_the_gate_on_variant():
    """Amazon snapshot products have no variants; a task with no required variant must not be gated on stock."""
    from catalog.providers.base import ReviewIds  # noqa: F401
    catalog = InMemoryCatalog()
    catalog.products["shoe-a"] = catalog.products["shoe-a"].model_copy(update={"variants": {}})
    task = feasible_task(hard_constraints=feasible_task().hard_constraints.model_copy(update={"required_variant": None}))
    trace = grounded_trace()
    rec = trace.outcome.recommendations[0].model_copy(update={"variant": "default"})
    trace = trace.model_copy(update={"outcome": trace.outcome.model_copy(update={"recommendations": (rec,)})})
    assert evaluate_gate(task, trace, catalog).value == 1
    # but a task that DOES require a variant still fails when the catalog cannot show it in stock
    required = feasible_task()
    assert evaluate_gate(required, trace, catalog).value == 0
