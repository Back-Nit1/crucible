"""In-memory-compatible implementation of the typed shopping tool surface."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Callable

from catalog.providers.base import FrozenCatalogProvider
from payments.guards import GuardedPayments, GuardViolation
from agents.actions import (
    Action, Compare, ConfirmAndPay, GetProduct, GetReviews, ParseIntent,
    ProposePurchase, RecordedToolCall, ReportNoMatch, SearchCatalog,
    SummarizeReviewEvidence,
)
from agents.state import EpisodeState


class InMemoryToolExecutor:
    def __init__(
        self, catalog: FrozenCatalogProvider, payments: GuardedPayments, *, task_id: str,
        agent_id: str, budget_cap: Decimal, min_candidates: int = 2,
        clock: Callable[[], dt.datetime] | None = None,
    ) -> None:
        self.catalog = catalog
        self.payments = payments
        self.task_id = task_id
        self.agent_id = agent_id
        self.budget_cap = budget_cap
        self.clock = clock or (lambda: dt.datetime.now(dt.timezone.utc))
        self.state = EpisodeState(catalog, min_candidates=min_candidates)
        self.records: list[RecordedToolCall] = []

    def execute(self, action: Action) -> RecordedToolCall:
        self.state.validate(action)
        references: tuple[str, ...] = ()
        summary = "action accepted"
        if isinstance(action, ParseIntent):
            summary = f"parsed category {action.category} with cap {action.max_total}"
        elif isinstance(action, SearchCatalog):
            products = self.catalog.search(action.query, action.filters)
            references = tuple(product.id for product in products)
            summary = f"returned {len(products)} catalog products"
        elif isinstance(action, GetProduct):
            product = self.catalog.get_product(action.product_id)
            references = (product.id,) if product else ()
            summary = "product detail found" if product else "product not found"
        elif isinstance(action, Compare):
            references = tuple(
                product_id for product_id in action.product_ids
                if self.catalog.get_product(product_id) is not None
            )
            summary = f"compared {len(references)} products"
        elif isinstance(action, GetReviews):
            reviews = self.catalog.get_reviews(action.product_id, action.focus, action.limit)
            if action.sort.value == "critical":
                reviews = sorted(reviews, key=lambda review: (review.rating, review.id))
            elif action.sort.value == "recent":
                reviews = sorted(reviews, key=lambda review: (review.date is None, review.date, review.id), reverse=True)
            references = tuple(review.id for review in reviews)
            summary = f"returned {len(reviews)} reviews"
        elif isinstance(action, SummarizeReviewEvidence):
            references = tuple(dict.fromkeys(
                review_id for claim in action.claims for review_id in claim.review_ids
            ))
            summary = f"grounded {len(action.claims)} claims"
        elif isinstance(action, ProposePurchase):
            try:
                pending = self.payments.propose_purchase(
                    self.task_id, self.agent_id, action.product_id, action.variant,
                    action.expected_total, self.budget_cap,
                )
            except GuardViolation as exc:
                record = RecordedToolCall(
                    sequence=len(self.records), action=action,
                    arguments=action.model_dump(mode="json", exclude={"type"}),
                    result_summary=f"payment guard rejected: {type(exc).__name__}",
                    error_code=type(exc).__name__, timestamp=self.clock(),
                )
                self.records.append(record)
                self.state.calls += 1
                raise
            references = (pending.id, pending.order_id)
            summary = "pending order created"
        elif isinstance(action, ConfirmAndPay):
            capture = self.payments.confirm_and_pay(action.pending_order_id, action.user_confirmed)
            references = (capture.order_id, capture.capture_id)
            summary = f"payment {capture.status}"
        elif isinstance(action, ReportNoMatch):
            references = (action.closest_product_id,) if action.closest_product_id else ()
            summary = "no realistic match reported"

        record = RecordedToolCall(
            sequence=len(self.records), action=action,
            arguments=action.model_dump(mode="json", exclude={"type"}),
            result_references=references, result_summary=summary, timestamp=self.clock(),
        )
        self.records.append(record)
        self.state.applied(action, references[:1] if isinstance(action, ProposePurchase) else references)
        return record
