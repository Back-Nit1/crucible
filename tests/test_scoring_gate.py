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
