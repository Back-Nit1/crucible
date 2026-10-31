"""Core-side contract for a complete, frozen training snapshot.

The live/routed search surface is intentionally insufficient for task ground truth:
generation needs deterministic enumeration and complete product-scoped review IDs.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from catalog.providers.base import CatalogProvider, Product


@runtime_checkable
class FrozenTrainingCatalog(CatalogProvider, Protocol):
    snapshot_id: str
    manifest_hash: str
    is_frozen_training_provider: bool

    def categories(self) -> tuple[str, ...]: ...
    def enumerate_products(self, category: str) -> tuple[Product, ...]: ...
    def complete_review_ids(self, product_id: str) -> frozenset[str]: ...


def require_frozen_training_catalog(catalog: CatalogProvider) -> FrozenTrainingCatalog:
    if not isinstance(catalog, FrozenTrainingCatalog):
        raise TypeError(
            "task generation requires snapshot_id, manifest_hash, categories(), "
            "enumerate_products(), and complete_review_ids()"
        )
    if catalog.is_frozen_training_provider is not True:
        raise ValueError("task generation accepts only an explicitly frozen training provider")
    if not catalog.snapshot_id or len(catalog.manifest_hash) != 64:
        raise ValueError("frozen provider requires a snapshot ID and SHA-256 manifest hash")
    return catalog


def complete_review_ids(catalog: CatalogProvider, product_id: str) -> frozenset[str]:
    lookup = getattr(catalog, "complete_review_ids", None)
    if lookup is None:
        raise TypeError("complete product-scoped review-ID lookup is required for grounding")
    ids = frozenset(lookup(product_id))
    if any(not review_id for review_id in ids):
        raise ValueError("complete review-ID lookup returned an empty ID")
    return ids
