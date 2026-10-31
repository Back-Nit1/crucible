"""All-in purchase quote (spec 8.4). Budget enforcement uses `Quote.total`, verified BEFORE any PayPal order is created.

`basis` says where the numbers came from, so nothing is silently treated as all-in:
  * "verified": a merchant/checkout source supplied subtotal, tax and shipping (live providers).
  * "snapshot_declared": a frozen snapshot has only a list price (Amazon Reviews 2023 has no tax or shipping data).
    The frozen world DEFINES list price as the all-in total; tax=0 and shipping=0 are that policy, not source data.
Callers that move real or sandbox money for a live listing should require "verified" (`GuardedPayments(require_verified=True)`)."""
import datetime as dt
from decimal import Decimal
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from catalog.providers.base import CatalogProvider

_CENT = Decimal("0.01")


class Quote(BaseModel):
    model_config = ConfigDict(frozen=True)

    product_id: str = Field(min_length=1)
    variant: str = ""
    subtotal: Decimal = Field(gt=0)
    tax: Decimal = Field(ge=0)
    shipping: Decimal = Field(ge=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    total: Decimal = Field(gt=0)
    source: str = Field(min_length=1)
    as_of: dt.datetime
    basis: Literal["verified", "snapshot_declared"]

    @model_validator(mode="after")
    def all_in_and_exact(self) -> "Quote":
        for name in ("subtotal", "tax", "shipping", "total"):
            v = getattr(self, name)
            if v != v.quantize(_CENT):
                raise ValueError(f"{name} must have at most 2 decimals, got {v}")
        if self.total != self.subtotal + self.tax + self.shipping:
            raise ValueError("total must equal subtotal + tax + shipping")
        if self.as_of.tzinfo is None:
            raise ValueError("as_of must be timezone-aware")
        return self


class QuoteProvider(Protocol):
    def quote(self, product_id: str, variant: str) -> Quote | None: ...


class SnapshotListPriceQuoter:
    """Quotes a snapshot product at its list price under the frozen-world all-in policy (basis=snapshot_declared)."""

    def __init__(self, catalog: CatalogProvider):
        self.catalog = catalog

    def quote(self, product_id: str, variant: str) -> Quote | None:
        p = self.catalog.get_product(product_id)
        if p is None:
            return None
        as_of = p.as_of if p.as_of.tzinfo else p.as_of.replace(tzinfo=dt.UTC)
        return Quote(product_id=p.id, variant=variant, subtotal=p.price, tax=Decimal("0.00"), shipping=Decimal("0.00"),
                     currency=p.currency, total=p.price, source=p.source, as_of=as_of, basis="snapshot_declared")
