"""Ledger records real payment state, in order, without anything secret or identifying."""
import datetime as dt
from decimal import Decimal as D

import pytest
from pydantic import ValidationError

from payments.errors import OrderNotApproved
from payments.guards import GuardedPayments, NotConfirmed, QuoteChanged
from payments.ledger import LedgerEntry, PaymentLedger, key_hash
from payments.mock import MockPayments
from tests.test_payments_contract import SECRET, _Catalog, _sandbox

T0 = dt.datetime(2026, 11, 1, 12, tzinfo=dt.UTC)


def _rig(kind):
    if kind == "mock":
        m = MockPayments(auto_approve=False)
        return m, m.approve, None
    r = _sandbox()
    return r.backend, r.approve, r.fake


@pytest.fixture(params=["mock", "sandbox"])
def setup(request):
    backend, approve, fake = _rig(request.param)
    ledger = PaymentLedger(request.param, clock=lambda: T0)
    g = GuardedPayments(backend, _Catalog(), ledger=ledger, clock=lambda: T0)
    return g, approve, ledger, fake


def test_lifecycle_events_are_ordered_and_typed(setup):
    g, approve, ledger, _ = setup
    p = g.propose_purchase("run-1", "a", "p1", "12", D("89.99"), D("100"))
    with pytest.raises(OrderNotApproved):  # confirmed but the buyer has not approved in PayPal
        g.confirm_and_pay(p.id, True)
    approve(p.order_id)
    g.record_approval(p.id, "APPROVED")
    cap = g.confirm_and_pay(p.id, True)
    again = g.confirm_and_pay(p.id, True)
    kinds = [(e.event, e.failure_code, e.idempotency_outcome) for e in ledger.entries("run-1")]
    assert kinds == [("proposal", None, "created"), ("confirmation", None, None), ("failure", "ORDER_NOT_APPROVED", None),
                     ("approval", None, None), ("confirmation", None, None), ("capture", None, "created"),
                     ("confirmation", None, None), ("capture", None, "replayed")]
    assert [e.seq for e in ledger.entries()] == list(range(8))
    last = ledger.entries()[-1]
    assert (last.order_ref, last.capture_ref, last.amount, last.currency) == (p.order_id, cap.capture_id, D("89.99"), "USD")
    assert again.replayed and len(ledger.captures()) == 1  # a replay is not a second charge


def test_unconfirmed_and_changed_quote_never_reach_capture(setup):
    g, approve, ledger, fake = setup
    p = g.propose_purchase("run-2", "a", "p1", "12", D("89.99"), D("100"))
    approve(p.order_id)
    with pytest.raises(NotConfirmed):
        g.confirm_and_pay(p.id, False)
    g.catalog.p = g.catalog.p.model_copy(update={"price": D("95.00")})
    with pytest.raises(QuoteChanged):
        g.confirm_and_pay(p.id, True)
    assert [e.failure_code for e in ledger.entries() if e.event == "failure"] == ["not_confirmed", "quote_changed"]
    assert not any(e.event in ("confirmation", "capture") for e in ledger.entries())
    if fake:
        assert not any(path.endswith("/capture") for _, path, _ in fake.calls)


def test_entries_are_sanitized(setup):
    g, approve, ledger, _ = setup
    p = g.propose_purchase("run-3", "a", "p1", "12", D("89.99"), D("100"))
    approve(p.order_id)
    g.confirm_and_pay(p.id, True)
    dump = "".join(e.model_dump_json() for e in ledger.entries())
    for forbidden in (p.backend_key, SECRET, "Bearer", "https://", "access_token", "dbg"):
        assert forbidden not in dump
    assert all(e.idempotency_key_hash == key_hash(p.backend_key) for e in ledger.entries() if e.idempotency_key_hash)
    with pytest.raises(ValidationError):  # no free-form fields can smuggle a body or PII in
        LedgerEntry(seq=0, at=T0, mode="mock", event="capture", payer_email="x@y.z")


def test_propose_failure_is_recorded_without_a_body():
    r = _sandbox()
    import httpx
    ledger = PaymentLedger("sandbox", clock=lambda: T0)
    g = GuardedPayments(r.backend, _Catalog(), ledger=ledger, clock=lambda: T0)
    r.fake.faults = [httpx.Response(400, json={"name": "INVALID_REQUEST", "message": "LEAK",
                                               "details": [{"issue": "MALFORMED_REQUEST_JSON"}]})]
    with pytest.raises(Exception):
        g.propose_purchase("run-4", "a", "p1", "12", D("89.99"), D("100"))
    (row,) = ledger.entries()
    assert (row.event, row.failure_code, row.run_id) == ("failure", "MALFORMED_REQUEST_JSON", "run-4") and "LEAK" not in row.model_dump_json()
