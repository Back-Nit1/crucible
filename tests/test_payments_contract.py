"""Mock/sandbox contract: identical scenarios, identical outcomes (spec 8.4).

The sandbox backend runs against a stateful fake of PayPal Orders v2 (httpx.MockTransport) so the
suite is offline and deterministic; the fake follows the response shapes in the official spec."""
import json
from datetime import datetime
from decimal import Decimal as D

import httpx
import pytest

from catalog.providers.base import Product
from payments.errors import (AmountMismatch, OrderNotApproved, OrderNotFound, PaymentDeclined,
                             PaymentError)
from payments.guards import BudgetViolation, GuardedPayments, NotConfirmed
from payments.mock import MockPayments
from payments.sandbox import SandboxPayments, money

SECRET = "s3cret-value"


class FakePayPal:
    """Orders v2 subset: token, create (idempotent on PayPal-Request-Id), get, capture."""

    def __init__(self):
        self.calls: list[tuple[str, str, dict]] = []
        self.orders: dict[str, dict] = {}
        self.by_req: dict[str, dict] = {}
        self.decline = False
        self.expire_next_token = False
        self.faults: list = []  # responses/exceptions served (in order) to the next non-token calls
        self.pending_capture = False

    def handler(self, req: httpx.Request) -> httpx.Response:
        self.calls.append((req.method, req.url.path, dict(req.headers)))
        if req.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "tok", "token_type": "Bearer",
                                             "expires_in": 32000})
        if self.faults:
            f = self.faults.pop(0)
            if isinstance(f, Exception):
                raise f
            return f
        if self.expire_next_token:
            self.expire_next_token = False
            return httpx.Response(401, json={"name": "AUTHENTICATION_FAILURE", "message": "x",
                                             "debug_id": "d"})
        parts = req.url.path.split("/")
        if req.method == "POST" and req.url.path == "/v2/checkout/orders":
            rid = req.headers["paypal-request-id"]
            if rid in self.by_req:
                return httpx.Response(200, json=self.by_req[rid])
            body = json.loads(req.content)
            oid = f"ORD{len(self.orders) + 1}"
            order = {"id": oid, "status": "PAYER_ACTION_REQUIRED", "intent": "CAPTURE",
                     "purchase_units": [body["purchase_units"][0]],
                     "links": [{"href": f"https://sandbox.paypal.test/pay/{oid}",
                                "rel": "payer-action", "method": "GET"}]}
            self.orders[oid] = self.by_req[rid] = order
            return httpx.Response(201, json=order)
        order = self.orders.get(parts[4]) if len(parts) > 4 else None
        if order is None:
            return self._err(404, "RESOURCE_NOT_FOUND", "INVALID_RESOURCE_ID")
        if req.method == "GET":
            return httpx.Response(200, json=order)
        if order["status"] == "COMPLETED":  # replay is 200 only for the same request id
            if req.headers["paypal-request-id"] == order["_cap_req"]:
                return httpx.Response(200, json=order)
            return self._err(422, "UNPROCESSABLE_ENTITY", "ORDER_ALREADY_CAPTURED")
        if order["status"] != "APPROVED":
            return self._err(422, "UNPROCESSABLE_ENTITY", "ORDER_NOT_APPROVED")
        amt = order["purchase_units"][0]["amount"]
        status = "DECLINED" if self.decline else "PENDING" if self.pending_capture else "COMPLETED"
        order["status"] = "COMPLETED"
        order["_cap_req"] = req.headers["paypal-request-id"]
        order["purchase_units"][0]["payments"] = {"captures": [
            {"id": f"CAP-{order['id']}", "status": status, "amount": amt}]}
        return httpx.Response(201, json=order)

    @staticmethod
    def _err(code, name, issue):
        return httpx.Response(code, json={"name": name, "message": "m", "debug_id": "dbg",
                                          "details": [{"issue": issue}]})

    def approve(self, oid):  # what the buyer's browser does
        self.orders[oid]["status"] = "APPROVED"


class Rig:
    """Uniform handle over a backend + its way of simulating buyer approval."""

    def __init__(self, backend, approve):
        self.backend, self.approve = backend, approve


@pytest.fixture(params=["mock", "sandbox"])
def rig(request):
    if request.param == "mock":
        m = MockPayments(auto_approve=False)
        return Rig(m, m.approve)
    return _sandbox()


def test_exact_amount_round_trip(rig):
    oid = rig.backend.create_order(D("89.99"), "USD", "k1")
    rig.approve(oid)
    cap = rig.backend.capture(oid)
    assert (cap.amount, cap.currency, cap.status) == (D("89.99"), "USD", "COMPLETED")


@pytest.mark.parametrize("bad", [D("89.999"), D("0"), D("-1")])
def test_inexact_or_nonpositive_amount_rejected(rig, bad):
    with pytest.raises(ValueError):
        rig.backend.create_order(bad, "USD", "k1")


def test_money_formats_two_decimals_never_float():
    assert money(D("100")) == "100.00" and money(D("0.1") + D("0.2")) == "0.30"


def test_idempotent_create_and_capture(rig):
    a = rig.backend.create_order(D("10.00"), "USD", "same")
    assert rig.backend.create_order(D("10.00"), "USD", "same") == a
    assert rig.backend.create_order(D("10.00"), "USD", "other") != a
    rig.approve(a)
    c1, c2 = rig.backend.capture(a), rig.backend.capture(a)
    assert c1.model_dump(exclude={"replayed"}) == c2.model_dump(exclude={"replayed"})
    assert (c1.replayed, c2.replayed) == (False, True)  # second call is a replay, not a second charge


def test_status_progression(rig):
    oid = rig.backend.create_order(D("5.00"), "USD", "k")
    assert rig.backend.get_status(oid) == "PAYER_ACTION_REQUIRED"
    assert rig.backend.approval_url(oid).startswith("https://")
    rig.approve(oid)
    assert rig.backend.get_status(oid) == "APPROVED"
    rig.backend.capture(oid)
    assert rig.backend.get_status(oid) == "COMPLETED"


def test_error_mapping_capture_before_approval_and_unknown_order(rig):
    oid = rig.backend.create_order(D("5.00"), "USD", "k")
    with pytest.raises(OrderNotApproved):
        rig.backend.capture(oid)
    with pytest.raises(OrderNotFound):
        rig.backend.capture("NOPE")
    with pytest.raises(OrderNotFound):
        rig.backend.get_status("NOPE")


# --- sandbox-only wire details -----------------------------------------------------------------
def test_sandbox_sends_request_ids_and_bearer():
    r = _sandbox()
    oid = r.backend.create_order(D("5.00"), "USD", "key-1")
    r.approve(oid)
    r.backend.capture(oid)
    posts = {p: h for m, p, h in r.fake.calls if m == "POST"}
    assert posts["/v2/checkout/orders"]["paypal-request-id"] == "key-1"
    assert posts[f"/v2/checkout/orders/{oid}/capture"]["paypal-request-id"] == f"capture-{oid}"
    assert posts["/v2/checkout/orders"]["authorization"] == "Bearer tok"


def test_sandbox_declined_capture_and_already_captured_replay():
    r = _sandbox()
    r.fake.decline = True
    oid = r.backend.create_order(D("5.00"), "USD", "k")
    r.approve(oid)
    with pytest.raises(PaymentDeclined):
        r.backend.capture(oid)
    # request-id replay window gone (different id) -> ORDER_ALREADY_CAPTURED -> rebuilt from GET
    r2 = _sandbox()
    oid = r2.backend.create_order(D("5.00"), "USD", "k")
    r2.approve(oid)
    first = r2.backend.capture(oid)
    r2.fake.orders[oid]["_cap_req"] = "expired"
    again = r2.backend.capture(oid)
    assert again.capture_id == first.capture_id and again.replayed


def test_sandbox_refreshes_token_once_on_401_and_never_leaks_secret():
    r = _sandbox()
    r.fake.expire_next_token = True
    r.backend.create_order(D("5.00"), "USD", "k")  # 401 -> new token -> succeeds
    with pytest.raises(PaymentError) as e:
        r.backend.capture("NOPE")
    assert SECRET not in repr(e.value) and e.value.debug_id == "dbg" and e.value.http_status == 404


def test_sandbox_amount_mismatch_is_caught():
    r = _sandbox()
    oid = r.backend.create_order(D("5.00"), "USD", "k")
    r.approve(oid)
    r.fake.orders[oid]["purchase_units"][0]["amount"]["value"] = "6.00"
    with pytest.raises(AmountMismatch):
        r.backend.capture(oid)


def test_sandbox_refuses_live_env(monkeypatch):
    monkeypatch.setenv("PAYPAL_ENV", "live")
    with pytest.raises(RuntimeError):
        SandboxPayments("id", SECRET)


# --- guards over a real backend ----------------------------------------------------------------
class _Catalog:
    def __init__(self, price="89.99"):
        self.p = Product(id="p1", title="Shoe", category="shoes", price=D(price),
                         variants={"12": 3}, source="test", as_of=datetime(2023, 9, 1))

    def get_product(self, pid):
        return self.p if pid == "p1" else None


def test_budget_rejected_before_any_api_call():
    r = _sandbox()
    g = GuardedPayments(r.backend, _Catalog("120.00"))
    with pytest.raises(BudgetViolation):
        g.propose_purchase("t", "a", "p1", "12", D("120.00"), D("100"))
    assert r.fake.calls == []  # not even an OAuth token request


def test_no_capture_call_without_explicit_confirmation():
    r = _sandbox()
    g = GuardedPayments(r.backend, _Catalog())
    pending = g.propose_purchase("t", "a", "p1", "12", D("89.99"), D("100"))
    with pytest.raises(NotConfirmed):
        g.confirm_and_pay(pending.id, user_confirmed=False)
    assert not any(p.endswith("/capture") for _, p, _ in r.fake.calls)
    r.approve(pending.order_id)
    assert g.confirm_and_pay(pending.id, True).amount == D("89.99")


def _sandbox() -> Rig:
    fake = FakePayPal()
    http = httpx.Client(base_url="https://api-m.sandbox.paypal.com",
                        transport=httpx.MockTransport(fake.handler))
    r = Rig(SandboxPayments("id", SECRET, client=http), fake.approve)
    r.fake = fake
    return r


# --- retries, redaction, duplicate capture ---------------------------------------------------------
def _resp(status, issue="X", name="N", message="LEAKY-PAYPAL-TEXT"):
    return httpx.Response(status, json={"name": name, "message": message, "debug_id": "dbg-77",
                                        "details": [{"issue": issue}]})


def test_transient_failures_retry_with_the_same_request_id_then_succeed():
    from payments.errors import PaymentUnavailable
    r = _sandbox()
    r.fake.faults = [_resp(503), httpx.ReadTimeout("slow")]
    oid = r.backend.create_order(D("5.00"), "USD", "key-r")
    posts = [h["paypal-request-id"] for m, p, h in r.fake.calls if p == "/v2/checkout/orders"]
    assert posts == ["key-r"] * 3 and len(r.fake.orders) == 1  # one order despite three attempts
    assert oid == "ORD1"
    r.fake.faults = [httpx.ConnectError("down")] * 3
    with pytest.raises(PaymentUnavailable) as e:
        r.backend.get_status(oid)
    assert e.value.code == "NETWORK_ERROR" and e.value.retryable


def test_timeout_after_retries_is_typed_and_retryable():
    from payments.errors import PaymentUnavailable
    r = _sandbox()
    r.fake.faults = [httpx.ReadTimeout("t")] * 3
    with pytest.raises(PaymentUnavailable) as e:
        r.backend.create_order(D("5.00"), "USD", "k")
    assert e.value.code == "TIMEOUT" and e.value.retryable and r.fake.orders == {}


def test_permanent_errors_are_not_retried_and_leak_nothing():
    r = _sandbox()
    r.fake.faults = [_resp(400, issue="INVALID_PARAMETER_SYNTAX")]
    with pytest.raises(PaymentError) as e:
        r.backend.create_order(D("5.00"), "USD", "k")
    assert not e.value.retryable and e.value.code == "INVALID_PARAMETER_SYNTAX"
    assert len([1 for m, p, _ in r.fake.calls if p == "/v2/checkout/orders"]) == 1
    text = f"{e.value!s} {e.value!r}"
    assert "LEAKY-PAYPAL-TEXT" not in text and "dbg-77" not in text


def test_pending_or_missing_capture_is_a_typed_error():
    r = _sandbox()
    r.fake.pending_capture = True
    oid = r.backend.create_order(D("5.00"), "USD", "k")
    r.approve(oid)
    with pytest.raises(PaymentError) as e:
        r.backend.capture(oid)
    assert e.value.code == "CAPTURE_PENDING" and e.value.retryable
    r.fake.orders[oid]["purchase_units"][0]["payments"] = {}
    with pytest.raises(PaymentError, match="CAPTURE_MISSING"):
        r.backend.capture(oid)


def test_oauth_failure_is_typed_without_body():
    fake = FakePayPal()
    http = httpx.Client(base_url="https://api-m.sandbox.paypal.com", transport=httpx.MockTransport(
        lambda req: _resp(401, issue="invalid_client", message="LEAKY-PAYPAL-TEXT")))
    with pytest.raises(PaymentError, match="AUTH_FAILED") as e:
        SandboxPayments("id", SECRET, client=http).create_order(D("5.00"), "USD", "k")
    assert "LEAKY" not in str(e.value) and SECRET not in repr(e.value) and fake.calls == []


def test_second_capture_with_a_different_request_id_never_charges_twice():
    r = _sandbox()
    oid = r.backend.create_order(D("5.00"), "USD", "k")
    r.approve(oid)
    r.backend.capture(oid)
    with pytest.raises(PaymentError, match="ORDER_ALREADY_CAPTURED"):
        r.backend._call("POST", f"/v2/checkout/orders/{oid}/capture", request_id="rogue", json={})
    assert len(r.fake.orders[oid]["purchase_units"][0]["payments"]["captures"]) == 1
