from datetime import datetime, timezone
from decimal import Decimal

import pytest

from agents.actions import (
    Compare, ConfirmAndPay, GetProduct, GetReviews, ParseIntent, ProposePurchase,
    SearchCatalog, SummarizeReviewEvidence,
)
from agents.executor import InMemoryToolExecutor
from agents.state import InvalidActionOrder
from payments.guards import GuardedPayments
from payments.mock import MockPayments
from scoring.schemas import ReviewClaim, ReviewSort
from tests.fixtures.scoring import InMemoryCatalog


NOW = datetime(2026, 10, 31, tzinfo=timezone.utc)


def executor():
    catalog = InMemoryCatalog()
    return InMemoryToolExecutor(catalog, GuardedPayments(MockPayments(), catalog), task_id="task-1",
                                agent_id="agent-1", budget_cap=Decimal("100.00"), clock=lambda: NOW)


def parse():
    return ParseIntent(raw_message="need shoes", category="running-shoes",
                       max_total=Decimal("100.00"), assumptions=("size 12 is exact",))


def researched(e):
    e.execute(parse())
    e.execute(SearchCatalog(query="", filters={"category": "running-shoes"}))
    e.execute(GetProduct(product_id="shoe-a"))
    e.execute(Compare(product_ids=("shoe-a", "shoe-b")))
    e.execute(GetReviews(product_id="shoe-a", focus="cushioning", sort=ReviewSort.CRITICAL, limit=2))


def test_action_order_and_payment_happy_path():
    e = executor()
    researched(e)
    e.execute(SummarizeReviewEvidence(
        product_id="shoe-a", user_context="needs support",
        claims=(ReviewClaim(concern="cushioning", claim="support evidence",
                            review_ids=("review-a-positive",)),)))
    pending = e.execute(ProposePurchase(product_id="shoe-a", variant="12",
                                        expected_total=Decimal("89.00"), assumptions=("size 12",)))
    paid = e.execute(ConfirmAndPay(pending_order_id=pending.result_references[0], user_confirmed=True))
    assert paid.result_summary == "payment COMPLETED"
    assert [call.sequence for call in e.records] == list(range(len(e.records)))


def test_parse_must_be_first_and_detail_reviews_comparison_are_required():
    e = executor()
    with pytest.raises(InvalidActionOrder, match="first"):
        e.execute(SearchCatalog(query="shoe"))
    e.execute(parse())
    e.execute(SearchCatalog(query="", filters={"category": "running-shoes"}))
    with pytest.raises(InvalidActionOrder, match="detail"):
        e.execute(GetReviews(product_id="shoe-a", limit=2))
    e.execute(GetProduct(product_id="shoe-a"))
    with pytest.raises(InvalidActionOrder, match="compare"):
        e.execute(ProposePurchase(product_id="shoe-a", variant="12",
                                  expected_total=Decimal("89.00"), assumptions=("size 12",)))


def test_review_summary_cannot_cite_foreign_or_unread_review():
    e = executor()
    researched(e)
    with pytest.raises(InvalidActionOrder, match="unconsulted"):
        e.execute(SummarizeReviewEvidence(
            product_id="shoe-a", user_context="support",
            claims=(ReviewClaim(concern="support", claim="bad citation",
                                review_ids=("review-b-positive",)),)))


def test_confirmation_needs_pending_order_and_explicit_confirmation():
    e = executor()
    e.execute(parse())
    with pytest.raises(InvalidActionOrder, match="pending"):
        e.execute(ConfirmAndPay(pending_order_id="missing", user_confirmed=True))
