"""In-memory backend for bulk training runs. Parity-tested against sandbox (spec 8.4)."""
from decimal import Decimal
from itertools import count

from payments.base import Capture


class MockPayments:
    def __init__(self):
        self._n = count(1)
        self._orders: dict[str, tuple[str, Decimal, str]] = {}  # order_id -> (key, amount, ccy)
        self._by_key: dict[str, str] = {}
        self._captures: dict[str, Capture] = {}
        self.ledger: list[Capture] = []

    def create_order(self, amount: Decimal, currency: str, idempotency_key: str) -> str:
        if idempotency_key in self._by_key:
            return self._by_key[idempotency_key]
        oid = f"MOCK-ORDER-{next(self._n)}"
        self._orders[oid] = (idempotency_key, amount, currency)
        self._by_key[idempotency_key] = oid
        return oid

    def capture(self, order_id: str) -> Capture:
        if order_id in self._captures:
            return self._captures[order_id]
        _, amount, ccy = self._orders[order_id]
        cap = Capture(order_id=order_id, capture_id=f"MOCK-CAP-{order_id}", amount=amount,
                      currency=ccy, status="COMPLETED")
        self._captures[order_id] = cap
        self.ledger.append(cap)
        return cap
