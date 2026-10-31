"""In-memory backend for bulk training runs. Parity-tested against sandbox (spec 8.4)."""
from decimal import Decimal
from itertools import count

from payments.base import Capture
from payments.errors import OrderNotApproved, OrderNotFound
from payments.sandbox import money


class MockPayments:
    """`auto_approve=True` models bulk training (no buyer); False mirrors sandbox, where the
    buyer must approve (`approve()`) before capture."""

    def __init__(self, auto_approve: bool = True):
        self.auto_approve = auto_approve
        self._n = count(1)
        self._orders: dict[str, tuple[str, Decimal, str]] = {}  # order_id -> (key, amount, ccy)
        self._by_key: dict[str, str] = {}
        self._status: dict[str, str] = {}
        self._captures: dict[str, Capture] = {}
        self.ledger: list[Capture] = []

    def create_order(self, amount: Decimal, currency: str, idempotency_key: str) -> str:
        if idempotency_key in self._by_key:
            return self._by_key[idempotency_key]
        money(amount)  # same amount validation as sandbox
        oid = f"MOCK-ORDER-{next(self._n)}"
        self._orders[oid] = (idempotency_key, amount, currency)
        self._by_key[idempotency_key] = oid
        self._status[oid] = "APPROVED" if self.auto_approve else "PAYER_ACTION_REQUIRED"
        return oid

    def approve(self, order_id: str) -> None:
        self._order(order_id)
        self._status[order_id] = "APPROVED"

    def get_status(self, order_id: str) -> str:
        self._order(order_id)
        return self._status[order_id]

    def approval_url(self, order_id: str) -> str:
        self._order(order_id)
        return f"https://mock.invalid/approve/{order_id}"

    def capture(self, order_id: str) -> Capture:
        _, amount, ccy = self._order(order_id)
        if order_id in self._captures:
            return self._captures[order_id]
        if self._status[order_id] != "APPROVED":
            raise OrderNotApproved("ORDER_NOT_APPROVED", order_id)
        cap = Capture(order_id=order_id, capture_id=f"MOCK-CAP-{order_id}", amount=amount,
                      currency=ccy, status="COMPLETED")
        self._captures[order_id] = cap
        self._status[order_id] = "COMPLETED"
        self.ledger.append(cap)
        return cap

    def _order(self, order_id: str) -> tuple[str, Decimal, str]:
        if order_id not in self._orders:
            raise OrderNotFound("RESOURCE_NOT_FOUND", order_id)
        return self._orders[order_id]
