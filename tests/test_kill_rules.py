from decimal import Decimal

from scoring.kill_rules import INITIAL_RULES, evaluate_kill_rules
from scoring.schemas import (
    EpisodeTrace,
    NoMatchOutcome,
    PaymentEvent,
    PaymentStatus,
    Recommendation,
    RecommendationOutcome,
    ReviewClaim,
    ReviewSort,
    ToolCall,
    ToolName,
)
from tests.fixtures.scoring import InMemoryCatalog, feasible_task, grounded_trace


def replace_trace(trace, **changes):
    return EpisodeTrace(**{**trace.model_dump(), **changes})


def rule_ids(trace):
    result = evaluate_kill_rules(feasible_task(), trace, InMemoryCatalog())
    return [decision.rule_id for decision in result.decisions]


def test_grounded_research_trace_survives_initial_rules():
    result = evaluate_kill_rules(feasible_task(), grounded_trace(), InMemoryCatalog())
    assert not result.killed
    assert result.decisions == ()


def test_kills_hallucinated_product():
    trace = replace_trace(
        grounded_trace(),
        outcome=RecommendationOutcome(
            recommendations=(
                Recommendation(
                    product_id="ghost", variant="12", expected_total=Decimal("80.00")
                ),
            )
        ),
    )
    assert "K001_HALLUCINATED_PRODUCT" in rule_ids(trace)


def test_kills_wrong_refusal():
    trace = replace_trace(
        grounded_trace(),
        outcome=NoMatchOutcome(
            reason="No match.",
            closest_product_id="shoe-a",
            why_it_misses="Incorrectly claimed the budget was too low.",
        ),
    )
    assert "K002_WRONG_REFUSAL" in rule_ids(trace)


def test_kills_budget_violation_attempt_before_capture():
    calls = grounded_trace().tool_calls + (
        ToolCall(
            sequence=4,
            name=ToolName.PROPOSE_PURCHASE,
            product_id="shoe-a",
            variant="12",
            amount=Decimal("101.00"),
            currency="USD",
            idempotency_key="task-1:agent-1:shoe-a:12",
        ),
    )
    assert "K003_BUDGET_VIOLATION" in rule_ids(replace_trace(grounded_trace(), tool_calls=calls))


def test_kills_insufficient_research_when_pick_was_not_opened():
    calls = tuple(
        call for call in grounded_trace().tool_calls if call.name is not ToolName.GET_PRODUCT
    )
    assert "K004_INSUFFICIENT_RESEARCH" in rule_ids(
        replace_trace(grounded_trace(), tool_calls=calls)
    )


def test_kills_duplicate_payment_with_distinct_captures():
    payments = (
        PaymentEvent(
            sequence=5,
            product_id="shoe-a",
            variant="12",
            amount=Decimal("89.00"),
            idempotency_key="purchase-key",
            status=PaymentStatus.COMPLETED,
            order_id="order-1",
            capture_id="capture-1",
        ),
        PaymentEvent(
            sequence=6,
            product_id="shoe-a",
            variant="12",
            amount=Decimal("89.00"),
            idempotency_key="purchase-key",
            status=PaymentStatus.COMPLETED,
            order_id="order-2",
            capture_id="capture-2",
        ),
    )
    assert "K005_DUPLICATE_PAYMENT" in rule_ids(
        replace_trace(grounded_trace(), payments=payments)
    )


def test_kills_fabricated_or_misattributed_review_evidence():
    outcome = RecommendationOutcome(
        recommendations=(
            Recommendation(
                product_id="shoe-a",
                variant="12",
                expected_total=Decimal("89.00"),
                review_claims=(
                    ReviewClaim(
                        concern="cushioning",
                        claim="Claim points to a review for another product.",
                        review_ids=("review-b-positive",),
                    ),
                ),
            ),
        )
    )
    assert "K006_FABRICATED_REVIEW_EVIDENCE" in rule_ids(
        replace_trace(grounded_trace(), outcome=outcome)
    )


def test_kills_skipped_reviews_when_catalog_has_them():
    calls = tuple(
        call for call in grounded_trace().tool_calls if call.name is not ToolName.GET_REVIEWS
    )
    assert "K007_SKIPPED_REVIEWS" in rule_ids(replace_trace(grounded_trace(), tool_calls=calls))


def test_kills_review_gaming_with_one_review_and_only_top_rating():
    calls = tuple(
        call for call in grounded_trace().tool_calls if call.name is not ToolName.GET_REVIEWS
    ) + (
        ToolCall(
            sequence=3,
            name=ToolName.GET_REVIEWS,
            product_id="shoe-a",
            review_ids=("review-a-positive",),
            review_focus="cushioning",
            review_sort=ReviewSort.RELEVANT,
            limit=1,
        ),
    )
    outcome = RecommendationOutcome(
        recommendations=(
            Recommendation(
                product_id="shoe-a",
                variant="12",
                expected_total=Decimal("89.00"),
                review_claims=(
                    ReviewClaim(
                        concern="cushioning",
                        claim="The review discusses cushioning support.",
                        review_ids=("review-a-positive",),
                    ),
                ),
            ),
        )
    )
    assert "K008_REVIEW_GAMING" in rule_ids(
        replace_trace(grounded_trace(), tool_calls=calls, outcome=outcome)
    )


def test_rule_registry_is_versioned_and_stably_ordered():
    assert [rule.id for rule in INITIAL_RULES] == [
        "K001_HALLUCINATED_PRODUCT",
        "K002_WRONG_REFUSAL",
        "K003_BUDGET_VIOLATION",
        "K004_INSUFFICIENT_RESEARCH",
        "K005_DUPLICATE_PAYMENT",
        "K006_FABRICATED_REVIEW_EVIDENCE",
        "K007_SKIPPED_REVIEWS",
        "K008_REVIEW_GAMING",
    ]
    assert all(rule.version == 1 for rule in INITIAL_RULES)
