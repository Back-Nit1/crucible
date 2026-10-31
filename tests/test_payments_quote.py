import datetime as dt
from decimal import Decimal as D

import pytest
from pydantic import ValidationError

from catalog.providers.base import Product
from payments.guards import BudgetViolation, GuardedPayments, PriceMismatch, QuoteNotVerified, QuoteStale
from payments.mock import MockPayments
from payments.quote import Quote, SnapshotListPriceQuoter

NOW = dt.datetime(2026, 11, 1, tzinfo=dt.UTC)


def quote(sub="80.00", tax="6.40", ship="5.00", total=None, basis="verified", as_of=NOW):
    t = total or str(D(sub) + D(tax) + D(ship))
    return Quote(product_id="p1", variant="12", subtotal=D(sub), tax=D(tax), shipping=D(ship), currency="USD",
                 total=D(t), source="merchant-x", as_of=as_of, basis=basis)


class Quoter:
    def __init__(self, q): self.q = q
    def quote(self, pid, variant): return self.q if pid == "p1" else None


class Cat:
    def get_product(self, pid):
        return Product(id="p1", title="s", category="shoes", price=D("80.00"), source="amazon2023", as_of=NOW) if pid == "p1" else None


class SpyBackend(MockPayments):
    created = 0
    def create_order(self, *a, **k):
        type(self).created += 1
        return super().create_order(*a, **k)


@pytest.fixture(autouse=True)
def reset():
    SpyBackend.created = 0


def guarded(q, **kw):
    return GuardedPayments(SpyBackend(), Cat(), Quoter(q), **kw)


def propose(g, total, cap):
    return g.propose_purchase("t", "a", "p1", "12", D(total), D(cap))


def test_quote_total_must_equal_components_exactly():
    with pytest.raises(ValidationError, match="subtotal \\+ tax \\+ shipping"):
        quote(total="91.41")
    assert quote().total == D("91.40")


def test_quote_rejects_fractional_cents_and_naive_timestamps():
    with pytest.raises(ValidationError):
        quote(sub="80.001", total="91.401")
    with pytest.raises(ValidationError, match="timezone"):
        quote(as_of=dt.datetime(2026, 1, 1))


def test_budget_is_enforced_on_the_all_in_total_before_any_order_exists():
    g = guarded(quote())  # list price 80.00 fits a 90.00 cap, all-in 91.40 does not
    with pytest.raises(BudgetViolation, match="91.40"):
        propose(g, "91.40", "90.00")
    assert SpyBackend.created == 0


def test_agent_quoting_the_list_price_is_a_price_mismatch_not_a_cheaper_charge():
    g = guarded(quote())
    with pytest.raises(PriceMismatch, match="quoted total 91.40"):
        propose(g, "80.00", "100.00")
    assert SpyBackend.created == 0


def test_order_is_created_for_the_exact_all_in_total_and_keeps_the_quote():
    g = guarded(quote())
    pending = propose(g, "91.40", "100.00")
    assert pending.total == D("91.40") and pending.quote.tax == D("6.40") and SpyBackend.created == 1
    assert g.confirm_and_pay(pending.id, True).amount == D("91.40")


def test_verified_total_required_rejects_snapshot_declared_quotes():
    g = guarded(quote(tax="0.00", ship="0.00", basis="snapshot_declared"), require_verified=True)
    with pytest.raises(QuoteNotVerified):
        propose(g, "80.00", "100.00")
    assert SpyBackend.created == 0


def test_stale_verified_quote_is_rejected():
    g = guarded(quote(as_of=NOW - dt.timedelta(hours=2)), max_quote_age=dt.timedelta(minutes=30), clock=lambda: NOW)
    with pytest.raises(QuoteStale):
        propose(g, "91.40", "100.00")


def test_snapshot_quoter_declares_its_basis_and_invents_no_tax_or_shipping_figures():
    q = SnapshotListPriceQuoter(Cat()).quote("p1", "12")
    assert (q.basis, q.subtotal, q.total, q.source) == ("snapshot_declared", D("80.00"), D("80.00"), "amazon2023")
    assert SnapshotListPriceQuoter(Cat()).quote("ghost", "") is None


def test_default_guard_still_treats_unknown_products_as_hallucinations():
    g = GuardedPayments(MockPayments(), Cat())
    with pytest.raises(PriceMismatch):
        g.propose_purchase("t", "a", "ghost", "", D("1.00"), D("5.00"))
