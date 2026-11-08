"""Safety guards wrapping every backend, in order (spec 7.1):
budget cap -> price re-check -> idempotency key -> create -> (user confirm) -> capture.
Any GuardViolation is a kill offense in the world (spec 8.3, 8.6)."""
import datetime as dt
import hashlib
import re
import time
from decimal import Decimal

from pydantic import BaseModel

from catalog.providers.base import CatalogProvider
from payments.base import Capture, PaymentsBackend
from payments.errors import PaymentError
from payments.ledger import PaymentLedger
from payments.quote import ItemPriceQuotes, Quote, QuoteProvider


class GuardViolation(Exception):
    """Base: raised before any money moves."""


class BudgetViolation(GuardViolation): ...
class PriceMismatch(GuardViolation): ...
class OutOfStock(GuardViolation): ...
class NotConfirmed(GuardViolation): ...
class QuoteStale(GuardViolation): ...  # quote expired before it was used
class QuoteChanged(GuardViolation): ...  # price, total, currency or product no longer matches the pending order
class QuoteIncomplete(GuardViolation): ...  # all-in total required but shipping/tax are unknown


class PendingOrder(BaseModel):
    id: str  # == idempotency key
    product_id: str
    variant: str
    total: Decimal
    currency: str
    order_id: str
    quote_id: str | None = None
    quote_basis: str = "item_price_only"
    task_id: str | None = None  # run / episode this order belongs to (ledger association)
    backend_key: str | None = None  # the PayPal-Request-Id used for create (hashed before it reaches the ledger)
    quote: Quote | None = None  # the full verified quote the order was created from (shipping/tax stay None if unknown)


MAX_PENDING = 1000


def idempotency_key(task_id: str, agent_id: str, product_id: str, variant: str) -> str:
    return hashlib.sha256("|".join((task_id, agent_id, product_id, variant)).encode()).hexdigest()[:32]


class GuardedPayments:
    """`quotes` decides the charged amount. Default = item price only (frozen snapshot, labelled as such);
    pass `require_all_in=True` with an all-in QuoteProvider for anything that charges real-looking totals."""

    def __init__(self, backend: PaymentsBackend, catalog: CatalogProvider, quotes: QuoteProvider | None = None,
                 require_all_in: bool = False, clock=lambda: dt.datetime.now(dt.UTC),
                 ledger: PaymentLedger | None = None):
        self.backend, self.catalog, self.ledger = backend, catalog, ledger
        self.quotes, self.require_all_in, self.clock = quotes or ItemPriceQuotes(), require_all_in, clock
        self._pending: dict[str, PendingOrder] = {}

    def _checked_quote(self, product, product_id: str, variant: str, budget_cap: Decimal | None) -> Quote:
        q = self.quotes.quote(product, variant, self.clock())
        if (q.product_id, q.variant) != (product_id, variant):
            raise QuoteChanged(f"quote is for {q.product_id}/{q.variant}, not {product_id}/{variant}")
        if q.currency != product.currency:
            raise QuoteChanged(f"quote currency {q.currency} != product currency {product.currency}")
        if not q.is_fresh(self.clock()):
            raise QuoteStale(q.quote_id)
        if self.require_all_in and not q.is_all_in:
            raise QuoteIncomplete(f"{q.quote_id}: shipping/tax unknown, all-in total required")
        if budget_cap is not None and q.total > budget_cap:  # budget safety is on the total actually charged
            raise BudgetViolation(f"quoted total {q.total} > cap {budget_cap}")
        return q

    def propose_purchase(self, task_id: str, agent_id: str, product_id: str, variant: str,
                         expected_total: Decimal, budget_cap: Decimal) -> PendingOrder:
        if expected_total > budget_cap:
            raise BudgetViolation(f"{expected_total} > cap {budget_cap}")
        product = self.catalog.get_product(product_id)
        if product is None:
            raise PriceMismatch(f"unknown product {product_id}")  # hallucination, caught here too
        if product.price > budget_cap:  # re-check against the live price, not the agent's claim
            raise BudgetViolation(f"{product.price} > cap {budget_cap}")
        if product.variants and product.variants.get(variant, 0) <= 0:
            raise OutOfStock(f"{product_id}/{variant}")
        q = self._checked_quote(product, product_id, variant, budget_cap)  # revalidated right before order creation
        if q.total != expected_total:
            raise PriceMismatch(f"quoted total {q.total} != expected {expected_total}")
        key = idempotency_key(task_id, agent_id, product_id, variant)
        old = self._pending.get(key)
        if old and (old.total, old.currency) == (q.total, q.currency):
            return old
        # The backend key binds the amount, so a changed quote can never replay an order created for another total.
        backend_key = hashlib.sha256(f"{key}|{q.total}|{q.currency}".encode()).hexdigest()[:32]
        t = time.perf_counter()
        order_id = self._timed_create(task_id, q, backend_key, t)
        while len(self._pending) >= MAX_PENDING:  # bound memory: the oldest unconfirmed order is forgotten (PayPal keeps it)
            self._pending.pop(next(iter(self._pending)))
        self._pending[key] = PendingOrder(id=key, product_id=product_id, variant=variant, total=q.total,
                                          currency=q.currency, order_id=order_id, quote_id=q.quote_id,
                                          quote_basis=q.basis, quote=q, task_id=task_id, backend_key=backend_key)
        return self._pending[key]

    def _record(self, event, order: "PendingOrder | None" = None, **fields) -> None:
        if self.ledger is not None:
            self.ledger.record(event, run_id=order.task_id if order else fields.pop("run_id", None),
                               order_ref=order.order_id if order else None,
                               idempotency_key=order.backend_key if order else None,
                               amount=order.total if order else None, currency=order.currency if order else None, **fields)

    def _timed_create(self, task_id: str, q: Quote, backend_key: str, t0: float) -> str:
        try:
            order_id = self.backend.create_order(q.total, q.currency, backend_key)
        except PaymentError as exc:
            self._record("failure", run_id=task_id, failure_code=exc.code, latency_ms=_ms(t0))
            raise
        if self.ledger is not None:
            self.ledger.record("proposal", run_id=task_id, order_ref=order_id, amount=q.total, currency=q.currency,
                               idempotency_key=backend_key, idempotency_outcome="created", latency_ms=_ms(t0))
        return order_id

    def pending(self, pending_id: str) -> PendingOrder | None:
        return self._pending.get(pending_id)

    def confirm_and_pay(self, pending_id: str, user_confirmed: bool) -> Capture:
        order = self._pending.get(pending_id)
        if not user_confirmed:
            self._record("failure", order, failure_code="not_confirmed")
            raise NotConfirmed(pending_id)
        order = self._pending[pending_id]
        try:
            self._revalidate(pending_id, order)
        except GuardViolation as exc:
            self._record("failure", order, failure_code=_snake(type(exc).__name__))
            raise
        self._record("confirmation", order)
        t = time.perf_counter()
        try:
            cap = self.backend.capture(order.order_id)  # backend idempotent
        except PaymentError as exc:
            self._record("failure", order, failure_code=exc.code, latency_ms=_ms(t))
            raise
        self._record("capture", order, capture_ref=cap.capture_id, status=cap.status, latency_ms=_ms(t),
                     idempotency_outcome="replayed" if cap.replayed else "created")
        return cap

    def _revalidate(self, pending_id: str, order: PendingOrder) -> None:
        if order.quote is not None and not order.quote.is_fresh(self.clock()):  # the quote the buyer saw has expired
            self._pending.pop(pending_id, None)
            raise QuoteStale(order.quote.quote_id)
        product = self.catalog.get_product(order.product_id)
        try:  # a price/quote change since the proposal invalidates the pending order
            if product is None:
                raise QuoteChanged(f"{order.product_id} disappeared")
            q = self._checked_quote(product, order.product_id, order.variant, None)
            if (q.total, q.currency) != (order.total, order.currency):
                raise QuoteChanged(f"quoted total {q.total} {q.currency} != pending {order.total} {order.currency}")
        except GuardViolation:
            self._pending.pop(pending_id, None)
            raise

    def record_approval(self, pending_id: str, status: str) -> None:
        """The buyer's PayPal approval as observed on the order. Approval is not confirmation and not capture."""
        if (order := self._pending.get(pending_id)) is not None:
            self._record("approval", order, status=status)


def _ms(t0: float) -> int:
    return round((time.perf_counter() - t0) * 1000)


def _snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()
