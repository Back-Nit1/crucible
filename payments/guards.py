"""Safety guards wrapping every backend, in order (spec 7.1):
budget cap -> price re-check -> idempotency key -> create -> (user confirm) -> capture.
Any GuardViolation is a kill offense in the world (spec 8.3, 8.6)."""
import hashlib
from decimal import Decimal

from pydantic import BaseModel

from catalog.providers.base import CatalogProvider
from payments.base import Capture, PaymentsBackend


class GuardViolation(Exception):
    """Base: raised before any money moves."""


class BudgetViolation(GuardViolation): ...
class PriceMismatch(GuardViolation): ...
class OutOfStock(GuardViolation): ...
class NotConfirmed(GuardViolation): ...


class PendingOrder(BaseModel):
    id: str  # == idempotency key
    product_id: str
    variant: str
    total: Decimal
    currency: str
    order_id: str


def idempotency_key(task_id: str, agent_id: str, product_id: str, variant: str) -> str:
    return hashlib.sha256("|".join((task_id, agent_id, product_id, variant)).encode()).hexdigest()[:32]


class GuardedPayments:
    def __init__(self, backend: PaymentsBackend, catalog: CatalogProvider):
        self.backend, self.catalog = backend, catalog
        self._pending: dict[str, PendingOrder] = {}

    def propose_purchase(self, task_id: str, agent_id: str, product_id: str, variant: str,
                         expected_total: Decimal, budget_cap: Decimal) -> PendingOrder:
        if expected_total > budget_cap:
            raise BudgetViolation(f"{expected_total} > cap {budget_cap}")
        product = self.catalog.get_product(product_id)
        if product is None:
            raise PriceMismatch(f"unknown product {product_id}")  # hallucination, caught here too
        if product.price != expected_total:
            raise PriceMismatch(f"listed {product.price} != expected {expected_total}")
        if product.price > budget_cap:  # re-check against the live price, not the agent's claim
            raise BudgetViolation(f"{product.price} > cap {budget_cap}")
        if product.variants and product.variants.get(variant, 0) <= 0:
            raise OutOfStock(f"{product_id}/{variant}")
        key = idempotency_key(task_id, agent_id, product_id, variant)
        if key in self._pending:
            return self._pending[key]
        order_id = self.backend.create_order(product.price, product.currency, key)
        self._pending[key] = PendingOrder(id=key, product_id=product_id, variant=variant,
                                          total=product.price, currency=product.currency,
                                          order_id=order_id)
        return self._pending[key]

    def confirm_and_pay(self, pending_id: str, user_confirmed: bool) -> Capture:
        if not user_confirmed:
            raise NotConfirmed(pending_id)
        return self.backend.capture(self._pending[pending_id].order_id)  # backend idempotent
