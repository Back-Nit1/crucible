from datetime import datetime
from decimal import Decimal as D

import pytest

from catalog.providers.base import Product
from payments.guards import (BudgetViolation, GuardedPayments, NotConfirmed, OutOfStock,
                             PriceMismatch)
from payments.mock import MockPayments


class FakeCatalog:
    def __init__(self, price="89.99"):
        self.p = Product(id="p1", title="Shoe", category="shoes", price=D(price),
                         variants={"12": 3, "13": 0}, source="test", as_of=datetime(2023, 9, 1))

    def get_product(self, pid):
        return self.p if pid == "p1" else None


def make(price="89.99"):
    backend = MockPayments()
    return backend, GuardedPayments(backend, FakeCatalog(price))


def propose(g, total="89.99", cap="100", variant="12", pid="p1"):
    return g.propose_purchase("t1", "a1", pid, variant, D(total), D(cap))


def test_happy_path_charges_exact_listed_price():
    backend, g = make()
    cap = g.confirm_and_pay(propose(g).id, user_confirmed=True)
    assert cap.amount == D("89.99") and backend.ledger == [cap]


def test_budget_cap_enforced():
    _, g = make("120.00")
    with pytest.raises(BudgetViolation):
        propose(g, total="120.00", cap="100")


def test_stale_price_rejected():
    _, g = make("95.00")  # catalog moved since agent looked
    with pytest.raises(PriceMismatch):
        propose(g, total="89.99")


def test_unknown_product_and_out_of_stock():
    _, g = make()
    with pytest.raises(PriceMismatch):
        propose(g, pid="ghost")
    with pytest.raises(OutOfStock):
        propose(g, variant="13")


def test_idempotent_retries_single_charge():
    backend, g = make()
    a, b = propose(g), propose(g)
    assert a.id == b.id
    g.confirm_and_pay(a.id, True)
    g.confirm_and_pay(a.id, True)
    assert len(backend.ledger) == 1


def test_requires_explicit_confirmation():
    backend, g = make()
    with pytest.raises(NotConfirmed):
        g.confirm_and_pay(propose(g).id, user_confirmed=False)
    assert backend.ledger == []
