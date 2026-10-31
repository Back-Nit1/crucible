"""CatalogProvider interface + core entities (spec 7.1, section 9)."""
import datetime as dt
from collections.abc import Iterator
from decimal import Decimal
from typing import Protocol

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


class Review(BaseModel):
    id: str
    product_id: str
    rating: float
    text: str
    date: dt.date | None = None
    helpful_votes: int = 0
    verified: bool = False
    reviewer_context: dict = Field(default_factory=dict)
    source_id: str | None = None  # the source dataset's own composed key, preserved separately from `id`


class CatalogProvider(Protocol):
    def search(self, query: str, filters: dict | None = None) -> list[Product]: ...
    def get_product(self, product_id: str) -> Product | None: ...
    def get_reviews(self, product_id: str, focus: str | None = None, limit: int = 10) -> list[Review]: ...


class SnapshotCatalog(CatalogProvider, Protocol):
    """A frozen catalog that can be enumerated completely. This is the only sanctioned enumeration path:
    an empty search query is NOT an enumeration mechanism (providers must reject it)."""

    def iter_products(self, category: str) -> Iterator[Product]:
        """Every product in `category`, in ascending product-id order, with no result cap."""

    def review_ids(self, product_id: str) -> frozenset[str]:
        """The complete set of review ids for one product. Never truncated; raises rather than returning a partial set."""

    def review_count(self, product_id: str) -> int: ...
