"""Adversarial all-in quote scenarios. Budget and the PayPal amount both come from quote.total."""
import datetime as dt
from datetime import datetime
from decimal import Decimal as D

import pytest
from pydantic import ValidationError

from catalog.providers.base import Product
from payments.guards import (BudgetViolation, GuardedPayments, PriceMismatch, QuoteChanged, QuoteIncomplete,
                             QuoteStale)
from payments.mock import MockPayments
from payments.quote import ItemPriceQuotes, MockQuotes, Quote

T0 = dt.datetime(2026, 11, 1, 12, tzinfo=dt.UTC)


class Cat:
    def __init__(self, price="80.00", ccy="USD"):
        self.p = Product(id="p1", title="Shoe", category="shoes", price=D(price), currency=ccy,
                         source="test", as_of=datetime(2023, 9, 1))

    def get_product(self, pid):
        return self.p if pid == "p1" else None


class Clock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now


def make(quotes, price="80.00", **kw):
    backend, clock, cat = MockPayments(), Clock(), Cat(price)
    return backend, clock, cat, GuardedPayments(backend, cat, quotes=quotes, clock=clock, **kw)


def propose(g, total, cap="100", pid="p1"):
    return g.propose_purchase("t", "a", pid, "std", D(total), D(cap))


def test_total_is_subtotal_plus_shipping_plus_tax_minus_discount_and_order_uses_it():
    backend, _, _, g = make(MockQuotes({"p1": D("5.00")}, {"p1": D("6.40")}, {"p1": D("1.00")}))
    p = propose(g, "90.40")
    assert (p.total, p.quote_basis) == (D("90.40"), "all_in")
    assert g.confirm_and_pay(p.id, True).amount == D("90.40") == backend.ledger[0].amount  # PayPal amount == total


def test_shipping_pushing_total_over_budget_is_rejected_even_though_item_price_fits():
    _, _, _, g = make(MockQuotes({"p1": D("30.00")}))  # item 80 <= 100, total 110 > 100
    with pytest.raises(BudgetViolation):
        propose(g, "80.00")  # agent claims item price
    with pytest.raises(BudgetViolation):
        propose(g, "110.00", cap="105")


def test_tax_pushing_total_over_budget_is_rejected():
    _, _, _, g = make(MockQuotes(tax={"p1": D("25.00")}))
    with pytest.raises(BudgetViolation):
        propose(g, "105.00", cap="100")


def test_agent_claiming_item_price_when_total_differs_is_a_price_mismatch():
    _, _, _, g = make(MockQuotes({"p1": D("5.00")}))
    with pytest.raises(PriceMismatch):
        propose(g, "80.00")  # real total is 85.00


def test_stale_quote_is_rejected():
    class Cached:  # provider serving a quote that expired before use
        def quote(self, product, variant, now):
            return ItemPriceQuotes().quote(product, variant, T0 - dt.timedelta(hours=1))
    _, _, _, g = make(Cached())
    with pytest.raises(QuoteStale):
        propose(g, "80.00")


def test_quote_expiring_before_confirmation_invalidates_the_pending_order():
    backend, clock, _, g = make(ItemPriceQuotes(ttl=dt.timedelta(minutes=5)))
    p = propose(g, "80.00")
    clock.now += dt.timedelta(minutes=1)
    assert g.confirm_and_pay(p.id, True).amount == D("80.00")  # re-quoted fresh, same total: fine
    assert len(backend.ledger) == 1


def test_price_change_after_proposal_invalidates_pending_and_blocks_capture():
    backend, _, cat, g = make(ItemPriceQuotes())
    p = propose(g, "80.00")
    cat.p = cat.p.model_copy(update={"price": D("85.00")})
    with pytest.raises(QuoteChanged):
        g.confirm_and_pay(p.id, True)
    assert backend.ledger == [] and p.id not in g._pending
    # a fresh proposal at the new price creates a NEW backend order; the old amount can't be replayed
    p2 = propose(g, "85.00")
    assert p2.order_id != p.order_id and p2.total == D("85.00")


def test_changed_currency_is_rejected():
    _, _, _, g = make(MockQuotes(currency="EUR"))
    with pytest.raises(QuoteChanged):
        propose(g, "80.00")


def test_quote_for_a_different_product_is_rejected():
    class Wrong:
        def quote(self, product, variant, now):
            return ItemPriceQuotes().quote(product.model_copy(update={"id": "other"}), variant, now)
    _, _, _, g = make(Wrong())
    with pytest.raises(QuoteChanged):
        propose(g, "80.00")


@pytest.mark.parametrize("field", ["discounts", "shipping", "tax"])
def test_negative_components_are_rejected(field):
    base = dict(quote_id="q", product_id="p1", variant="v", currency="USD", subtotal=D("80.00"), total=D("80.00"),
                basis="item_price_only", source="t", quoted_at=T0, expires_at=T0 + dt.timedelta(minutes=5))
    with pytest.raises(ValidationError):
        Quote(**{**base, field: D("-10.00")})


def test_discount_cannot_exceed_charges_and_total_must_add_up():
    base = dict(quote_id="q", product_id="p1", variant="v", currency="USD", subtotal=D("80.00"), basis="item_price_only",
                source="t", quoted_at=T0, expires_at=T0 + dt.timedelta(minutes=5))
    with pytest.raises(ValidationError):
        Quote(**base, discounts=D("90.00"), total=D("0.01"))
    with pytest.raises(ValidationError):
        Quote(**base, total=D("70.00"))  # understated total


def test_unknown_shipping_and_tax_are_unknown_not_zero():
    q = ItemPriceQuotes().quote(Cat().p, "std", T0)
    assert (q.shipping, q.tax, q.is_all_in) == (None, None, False)
    with pytest.raises(ValidationError):  # an all_in basis cannot hide unknown components
        Quote(**{**q.model_dump(), "basis": "all_in"})


def test_require_all_in_refuses_item_price_only_quotes():
    _, _, _, g = make(ItemPriceQuotes(), require_all_in=True)
    with pytest.raises(QuoteIncomplete):
        propose(g, "80.00")


def test_mock_quotes_are_deterministic():
    a, b = MockQuotes({"p1": D("5.00")}), MockQuotes({"p1": D("5.00")})
    assert a.quote(Cat().p, "std", T0) == b.quote(Cat().p, "std", T0)
