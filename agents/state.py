"""Deterministic action-order enforcement for one shopping episode."""

from __future__ import annotations

from dataclasses import dataclass, field

from catalog.providers.base import FrozenCatalogProvider
from agents.actions import (
    Action, Compare, ConfirmAndPay, GetProduct, GetReviews, ParseIntent,
    ProposePurchase, ReportNoMatch, SearchCatalog, SummarizeReviewEvidence,
)


class InvalidActionOrder(ValueError):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass
class EpisodeState:
    catalog: FrozenCatalogProvider
    min_candidates: int = 2
    calls: int = 0
    parsed: bool = False
    discovered: set[str] = field(default_factory=set)
    opened: set[str] = field(default_factory=set)
    compared: set[str] = field(default_factory=set)
    consulted_reviews: dict[str, set[str]] = field(default_factory=dict)
    pending_orders: set[str] = field(default_factory=set)
    terminated: bool = False

    def validate(self, action: Action) -> None:
        if self.terminated:
            raise InvalidActionOrder("episode_terminated", "no action is allowed after termination")
        if self.calls == 0 and not isinstance(action, ParseIntent):
            raise InvalidActionOrder("parse_intent_first", "parse_intent must be the first action")
        if self.calls > 0 and isinstance(action, ParseIntent):
            raise InvalidActionOrder("duplicate_parse", "parse_intent may only occur first")
        if not self.parsed and not isinstance(action, ParseIntent):
            raise InvalidActionOrder("intent_missing", "intent must be parsed before research")
        if isinstance(action, (GetProduct, GetReviews, SummarizeReviewEvidence, ProposePurchase)):
            if action.product_id not in self.discovered and not isinstance(action, GetProduct):
                raise InvalidActionOrder("product_not_discovered", "product must appear in search or lookup")
        if isinstance(action, GetReviews) and action.product_id not in self.opened:
            raise InvalidActionOrder("detail_not_opened", "open product detail before reviews")
        if isinstance(action, Compare):
            unknown = set(action.product_ids) - self.discovered
            if unknown:
                raise InvalidActionOrder("compare_unknown", f"cannot compare unknown products: {sorted(unknown)}")
        if isinstance(action, SummarizeReviewEvidence):
            consulted = self.consulted_reviews.get(action.product_id, set())
            cited = {review_id for claim in action.claims for review_id in claim.review_ids}
            if not cited <= consulted:
                raise InvalidActionOrder("review_not_consulted", "summary cites an unconsulted review ID")
            valid = self.catalog.get_review_ids(action.product_id).ids
            if not cited <= valid:
                raise InvalidActionOrder("review_not_found", "summary cites a nonexistent or foreign review")
        if isinstance(action, ProposePurchase):
            if action.product_id not in self.opened:
                raise InvalidActionOrder("detail_not_opened", "selected product detail was not opened")
            required = min(self.min_candidates, len(self.discovered))
            if len(self.compared) < required:
                raise InvalidActionOrder("insufficient_comparison", f"compare at least {required} candidates")
            if self.catalog.get_reviews(action.product_id, limit=1) and not self.consulted_reviews.get(action.product_id):
                raise InvalidActionOrder("reviews_not_checked", "available reviews must be checked")
        if isinstance(action, ConfirmAndPay):
            if action.pending_order_id not in self.pending_orders:
                raise InvalidActionOrder("pending_order_missing", "confirm_and_pay needs an existing pending order")
            if not action.user_confirmed:
                raise InvalidActionOrder("confirmation_missing", "explicit confirmation is required")
        if isinstance(action, ReportNoMatch) and self.discovered and action.closest_product_id is None:
            raise InvalidActionOrder("closest_product_missing", "a discovered closest product is required")

    def applied(self, action: Action, references: tuple[str, ...]) -> None:
        self.calls += 1
        if isinstance(action, ParseIntent):
            self.parsed = True
        elif isinstance(action, SearchCatalog):
            self.discovered.update(references)
        elif isinstance(action, GetProduct):
            self.discovered.update(references)
            if references:
                self.opened.add(action.product_id)
        elif isinstance(action, Compare):
            self.compared.update(action.product_ids)
        elif isinstance(action, GetReviews):
            self.consulted_reviews.setdefault(action.product_id, set()).update(references)
        elif isinstance(action, ProposePurchase):
            self.pending_orders.update(references)
        elif isinstance(action, (ConfirmAndPay, ReportNoMatch)):
            self.terminated = True
