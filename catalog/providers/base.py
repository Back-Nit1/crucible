"""CatalogProvider interface + core entities (spec 7.1, section 9)."""
import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterator, Protocol

from pydantic import BaseModel, Field


class Product(BaseModel):
    id: str
    title: str
    brand: str | None = None
    category: str
    price: Decimal
    currency: str = "USD"
    variants: dict[str, int] = Field(default_factory=dict)  # variant -> units in stock
    attributes: dict = Field(default_factory=dict)
    source: str  # e.g. "amazon2023", "channel3"; shown in the UI
    as_of: dt.datetime  # snapshot / fetch time; shown in the UI
    snapshot: bool = False  # True = frozen snapshot record, never live data
    manifest_hash: str | None = None  # category manifest the record was served under (snapshot only)
    source_product_id: str | None = None  # id in the origin dataset, kept for provenance (Amazon: parent_asin)


class Review(BaseModel):
    id: str  # canonical, collision-free (see catalog.indexing.canonical_review_id)
    product_id: str
    source_review_id: str | None = None  # id as composed from the origin dataset; cite/trace with this
    rating: float
    text: str
    date: dt.date | None = None
    helpful_votes: int = 0
    verified: bool = False
    reviewer_context: dict = Field(default_factory=dict)


class CatalogProvider(Protocol):
    def search(self, query: str, filters: dict | None = None) -> list[Product]: ...
    def get_product(self, product_id: str) -> Product | None: ...
    def get_reviews(self, product_id: str, focus: str | None = None, limit: int = 10) -> list[Review]: ...


class SnapshotMismatch(Exception):
    """Requested manifest hash is not the snapshot this provider serves."""


class IncompleteReviewIds(Exception):
    """Provider could not prove it returned every stored review id (never truncate silently)."""


@dataclass(frozen=True)
class ReviewIds:
    """Complete product-scoped review-id set. `product_found=False` means the product is not in the catalog."""
    product_found: bool
    ids: frozenset[str] = frozenset()


class FrozenCatalogProvider(CatalogProvider, Protocol):
    """Snapshot-only provider: explicit enumeration and complete review ids, no search ranking involved."""

    def iter_products(self, category: str, manifest_hash: str) -> Iterator[Product]:
        """Every product of `category`, ordered by product id, no limit. Raises SnapshotMismatch on a wrong hash."""

    def get_review_ids(self, product_id: str) -> ReviewIds:
        """All stored review ids of the product (complete or raises IncompleteReviewIds)."""
