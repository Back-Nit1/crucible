"""All-in quote contract (Phase 3). `Product.price` is the item price, not necessarily what is charged.

Rules enforced here and in GuardedPayments:
- budget safety and the PayPal order amount both use `quote.total`;
- shipping/tax are `None` (unknown) unless the provider knows them; unknown is never treated as zero;
- an `item_price_only` quote is allowed only where the caller explicitly accepts it (frozen training tasks,
  labelled demo) and is never presented as a live all-in total."""
import datetime as dt
import hashlib
from decimal import Decimal
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from catalog.providers.base import Product

CENT = Decimal("0.01")
Money = Decimal


class QuoteError(Exception):
    """Base for quote problems; the guard layer re-raises these as GuardViolation subclasses."""


class Quote(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    quote_id: str
    product_id: str
    variant: str
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    subtotal: Decimal = Field(gt=0)
    shipping: Decimal | None = Field(default=None, ge=0)  # None = unknown, NOT free
    tax: Decimal | None = Field(default=None, ge=0)  # None = unknown, NOT zero
    discounts: Decimal = Field(default=Decimal(0), ge=0)  # amount subtracted; negative is rejected
    total: Decimal
    basis: Literal["all_in", "item_price_only"]
    source: str
    quoted_at: dt.datetime
    expires_at: dt.datetime

    @model_validator(mode="after")
    def consistent(self) -> "Quote":
        for name in ("subtotal", "shipping", "tax", "discounts", "total"):
            v = getattr(self, name)
            if v is not None and v != v.quantize(CENT):
                raise ValueError(f"{name} must have at most 2 decimals")
        known = self.subtotal + (self.shipping or 0) + (self.tax or 0)
        if self.discounts > known:
            raise ValueError("discounts exceed the quoted charges")
        if self.total != known - self.discounts or self.total <= 0:
            raise ValueError("total must equal subtotal + shipping + tax - discounts")
        if self.basis == "all_in" and (self.shipping is None or self.tax is None):
            raise ValueError("an all_in quote needs known shipping and tax")
        if self.expires_at <= self.quoted_at:
            raise ValueError("expires_at must follow quoted_at")
        return self

    @property
    def is_all_in(self) -> bool:
        return self.basis == "all_in"

    def is_fresh(self, now: dt.datetime) -> bool:
        return self.quoted_at <= now < self.expires_at


class QuoteProvider(Protocol):
    def quote(self, product: Product, variant: str, now: dt.datetime) -> Quote: ...


def _quote_id(*parts: object) -> str:
    return "q-" + hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:24]


class ItemPriceQuotes:
    """Frozen-snapshot quotes: the catalog item price only. Shipping/tax stay unknown and the basis says so."""

    def __init__(self, ttl: dt.timedelta = dt.timedelta(minutes=15)):
        self.ttl = ttl

    def quote(self, product: Product, variant: str, now: dt.datetime) -> Quote:
        return Quote(quote_id=_quote_id(product.id, variant, product.price, product.currency, now.isoformat()),
                     product_id=product.id, variant=variant, currency=product.currency, subtotal=product.price,
                     total=product.price, basis="item_price_only", source=product.source,
                     quoted_at=now, expires_at=now + self.ttl)


class MockQuotes:
    """Deterministic all-in quotes for tests and mock worlds: fixed shipping/tax/discount per product id."""

    def __init__(self, shipping: dict[str, Decimal] | None = None, tax: dict[str, Decimal] | None = None,
                 discounts: dict[str, Decimal] | None = None, ttl: dt.timedelta = dt.timedelta(minutes=15),
                 currency: str | None = None):
        self.shipping, self.tax, self.discounts = shipping or {}, tax or {}, discounts or {}
        self.ttl, self.currency = ttl, currency

    def quote(self, product: Product, variant: str, now: dt.datetime) -> Quote:
        ship, tax = self.shipping.get(product.id, Decimal(0)), self.tax.get(product.id, Decimal(0))
        disc = self.discounts.get(product.id, Decimal(0))
        ccy = self.currency or product.currency
        total = product.price + ship + tax - disc
        return Quote(quote_id=_quote_id(product.id, variant, total, ccy, now.isoformat()), product_id=product.id,
                     variant=variant, currency=ccy, subtotal=product.price, shipping=ship, tax=tax, discounts=disc,
                     total=total, basis="all_in", source="mock-quotes", quoted_at=now, expires_at=now + self.ttl)
