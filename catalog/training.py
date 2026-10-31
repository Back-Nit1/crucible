"""CatalogProvider view of the frozen training/eval snapshot, bound to ProviderRouter(mode="training").

Agent-facing contract (what tasks/agents/scoring call):
  * `enumerate(category)` / `search("", {"category": c})`: documented, COMPLETE, id-ordered category enumeration.
    The empty-query form exists only because `tasks.engine.build_task` calls it; it is routed to the explicit
    enumeration path, never to a ranked search.
  * `search(query, filters)`: ranked search (non-empty query).
  * `get_reviews(product_id, limit)`: with no focus and limit >= COMPLETE (10,000) returns EVERY review of the product
    (the listing used for review-id validation); smaller limits return that many. With a focus it is relevance search.
"""
from collections.abc import Iterator
from decimal import Decimal

from catalog.providers.base import Product, Review
from catalog.router import ProviderRouter

COMPLETE = 10_000


class TrainingCatalog:
    def __init__(self, router: ProviderRouter, mode: str = "training"):
        if mode not in ("training", "eval"):
            raise ValueError("TrainingCatalog serves frozen snapshots only (training/eval)")
        self.router, self.mode = router, mode

    def enumerate(self, category: str) -> Iterator[Product]:
        yield from self.router.enumerate_products(category, self.mode).products

    def search(self, query: str, filters: dict | None = None) -> list[Product]:
        f = filters or {}
        if not query.strip():
            if not f.get("category"):
                raise ValueError("enumeration requires a category")
            prods = list(self.enumerate(f["category"]))
            if f.get("max_price") is not None:
                prods = [p for p in prods if p.price <= Decimal(str(f["max_price"]))]
            if f.get("min_price") is not None:
                prods = [p for p in prods if p.price >= Decimal(str(f["min_price"]))]
            return prods
        return self.router.search(query, f, mode=self.mode).products

    def get_product(self, product_id: str) -> Product | None:
        return self.router.get_product(product_id, mode=self.mode).product

    def get_reviews(self, product_id: str, focus: str | None = None, limit: int = 10) -> list[Review]:
        return self.router.get_reviews(product_id, focus, limit, mode=self.mode).reviews
