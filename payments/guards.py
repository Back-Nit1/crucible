"""Safety guards wrapping every backend, in order (spec 7.1):
budget cap -> price re-check -> idempotency key -> create -> (user confirm) -> capture.
Any GuardViolation is a kill offense in the world (spec 8.3, 8.6)."""
import datetime as dt
import hashlib
from decimal import Decimal

from pydantic import BaseModel

from catalog.providers.base import CatalogProvider
from payments.base import Capture, PaymentsBackend
from payments.quote import Quote, QuoteProvider, SnapshotListPriceQuoter


class GuardViolation(Exception):
    """Base: raised before any money moves."""


class BudgetViolation(GuardViolation): ...
class PriceMismatch(GuardViolation): ...
class OutOfStock(GuardViolation): ...
class NotConfirmed(GuardViolation): ...
class QuoteNotVerified(GuardViolation):
    """The quote's tax/shipping are not source data but this backend requires a verified all-in total."""
class QuoteStale(GuardViolation): ...


class PendingOrder(BaseModel):
    id: str  # == idempotency key
    product_id: str
    variant: str
    total: Decimal
    currency: str
    order_id: str
    quote: Quote | None = None  # the verified all-in quote the order was created from


def idempotency_key(task_id: str, agent_id: str, product_id: str, variant: str) -> str:
    return hashlib.sha256("|".join((task_id, agent_id, product_id, variant)).encode()).hexdigest()[:32]


class GuardedPayments:
    """Order of checks, all before any order exists: agent claim vs cap -> all-in quote -> quote basis/age ->
    verified total vs cap -> expected_total == quote.total -> stock -> idempotency -> create."""

    def __init__(self, backend: PaymentsBackend, catalog: CatalogProvider, quoter: QuoteProvider | None = None,
                 require_verified: bool = False, max_quote_age: dt.timedelta | None = None,
                 clock=lambda: dt.datetime.now(dt.UTC)):
        self.backend, self.catalog = backend, catalog
        self.quoter = quoter or SnapshotListPriceQuoter(catalog)
        self.require_verified, self.max_quote_age, self.clock = require_verified, max_quote_age, clock
        self._pending: dict[str, PendingOrder] = {}

    def propose_purchase(self, task_id: str, agent_id: str, product_id: str, variant: str,
                         expected_total: Decimal, budget_cap: Decimal) -> PendingOrder:
        if expected_total > budget_cap:
            raise BudgetViolation(f"{expected_total} > cap {budget_cap}")
        quote = self.quoter.quote(product_id, variant)
        if quote is None:
            raise PriceMismatch(f"unknown product {product_id}")  # hallucination, caught here too
        if self.require_verified and quote.basis != "verified":
            raise QuoteNotVerified(f"{product_id}: {quote.basis} quote is not an all-in verified total")
        if self.max_quote_age is not None and self.clock() - quote.as_of > self.max_quote_age:
            raise QuoteStale(f"{product_id}: quote as of {quote.as_of.isoformat()}")
        if quote.total > budget_cap:  # the verified all-in total, not the agent's claim and not the list price
            raise BudgetViolation(f"{quote.total} > cap {budget_cap}")
        if quote.total != expected_total:
            raise PriceMismatch(f"quoted total {quote.total} != expected {expected_total}")
        product = self.catalog.get_product(product_id)
        if product is not None and product.variants and product.variants.get(variant, 0) <= 0:
            raise OutOfStock(f"{product_id}/{variant}")
        key = idempotency_key(task_id, agent_id, product_id, variant)
        if key in self._pending:
            return self._pending[key]
        order_id = self.backend.create_order(quote.total, quote.currency, key)
        self._pending[key] = PendingOrder(id=key, product_id=product_id, variant=variant, total=quote.total,
                                          currency=quote.currency, order_id=order_id, quote=quote)
        return self._pending[key]

    def confirm_and_pay(self, pending_id: str, user_confirmed: bool) -> Capture:
        if not user_confirmed:
            raise NotConfirmed(pending_id)
        return self.backend.capture(self._pending[pending_id].order_id)  # backend idempotent
