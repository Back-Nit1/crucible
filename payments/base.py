"""PaymentsBackend interface (spec 7.1). Guards live in payments/guards.py."""
from decimal import Decimal
from typing import Protocol

from pydantic import BaseModel


class Capture(BaseModel):
    order_id: str
    capture_id: str
    amount: Decimal
    currency: str
    status: str  # "COMPLETED"
    replayed: bool = False  # True when this call returned an already-made capture (no new charge)


class PaymentsBackend(Protocol):
    """Backends must be idempotent on `idempotency_key` (PayPal-Request-Id semantics)."""

    def create_order(self, amount: Decimal, currency: str, idempotency_key: str) -> str: ...
    def capture(self, order_id: str) -> Capture: ...
