"""Fail-closed access to the frozen snapshot's complete review-ID index."""

from __future__ import annotations

from catalog.providers.base import CatalogProvider


class CompleteReviewLookupUnavailable(RuntimeError):
    pass


def complete_review_ids(catalog: CatalogProvider, product_id: str) -> frozenset[str]:
    """Return all product-scoped IDs without relying on a retrieval limit.

    ``TrainingCatalog`` intentionally wraps the platform router, so this consumer
    bridge supports both a direct ``SnapshotCatalog`` and that integrated view.
    Anything else fails closed instead of treating a truncated top-k as complete.
    """
    lookup = getattr(catalog, "review_ids", None)
    if callable(lookup):
        return frozenset(lookup(product_id))
    router = getattr(catalog, "router", None)
    mode = getattr(catalog, "mode", None)
    router_lookup = getattr(router, "review_ids", None)
    if callable(router_lookup) and mode in {"training", "eval"}:
        return frozenset(router_lookup(product_id, mode=mode))
    raise CompleteReviewLookupUnavailable(
        "grounding requires SnapshotCatalog.review_ids or a frozen TrainingCatalog"
    )
