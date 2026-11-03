"""PAYMENTS_BACKEND=sandbox wiring in the REST API: ledger, 503 mapping, and the capture gates."""
from decimal import Decimal

import httpx
from fastapi.testclient import TestClient

from api.main import create_app
from catalog.router import ProviderRouter
from payments.sandbox import SandboxPayments
from tests.test_api_endpoints import CFG, PROPOSE, Snap
from tests.test_payments_contract import FakePayPal

URL = "/purchase/confirm"


def sandbox_client(snap=None):
    fake = FakePayPal()
    sb = SandboxPayments("id", "s", client=httpx.Client(base_url="https://api-m.sandbox.paypal.com",
                                                         transport=httpx.MockTransport(fake.handler)), sleep=lambda _: None)
    c = TestClient(create_app(ProviderRouter({"elastic_snapshot": snap or Snap()}, CFG), sb), raise_server_exceptions=False)
    return c, fake


def captures(fake):
    return [p for _, p, _ in fake.calls if p.endswith("/capture")]


def test_ledger_serves_real_sandbox_calls_sanitized_and_read_only():
    c, fake = sandbox_client()
    p = c.post("/purchase/propose", json=PROPOSE).json()
    fake.approve("ORD1")
    assert c.post(URL, json={"pending_order_id": p["pending_order_id"], "user_confirmed": True}).status_code == 200
    page = c.get("/payments/ledger").json()
    assert [r["event"] for r in page["items"]] == ["proposal", "confirmation", "capture"] and {r["mode"] for r in page["items"]} == {"sandbox"}
    assert page["items"][-1]["references"][0] == "ORD1" and page["items"][-1]["amount"] == "80.00"
    assert "approval_url" not in c.get("/payments/ledger").text and "paypal.com" not in c.get("/payments/ledger").text
    assert c.post("/payments/ledger").status_code == 405  # read-only


def test_without_a_sandbox_backend_the_ledger_stays_the_world_run_view(monkeypatch):
    from tests.test_api_endpoints import client
    assert client().get("/payments/ledger").status_code == 503  # no trace store configured; never invents sandbox rows


def test_no_capture_without_user_confirmed_even_when_approved():
    c, fake = sandbox_client()
    p = c.post("/purchase/propose", json=PROPOSE).json()
    fake.approve("ORD1")
    r = c.post(URL, json={"pending_order_id": p["pending_order_id"], "user_confirmed": False})
    assert r.status_code == 428 and not captures(fake)
    assert c.post(URL, json={"pending_order_id": p["pending_order_id"]}).status_code == 422 and not captures(fake)


def test_no_capture_for_stale_quote_or_over_budget():
    class Moved(Snap):  # the listed price moved after the quote
        pass
    snap = Moved()
    c, fake = sandbox_client(snap)
    p = c.post("/purchase/propose", json=PROPOSE).json()
    fake.approve("ORD1")
    snap.items = [snap.items[0].model_copy(update={"price": Decimal("95.00")})]
    r = c.post(URL, json={"pending_order_id": p["pending_order_id"], "user_confirmed": True})
    assert r.status_code == 409 and not captures(fake)
    c2, fake2 = sandbox_client()
    assert c2.post("/purchase/propose", json=PROPOSE | {"budget_cap": "50.00"}).status_code == 409 and not fake2.orders


def test_paypal_unreachable_is_503_retryable_not_402_and_does_not_double_charge():
    c, fake = sandbox_client()
    p = c.post("/purchase/propose", json=PROPOSE).json()
    fake.approve("ORD1")
    fake.faults = [httpx.ReadTimeout("secret-host")] * 3
    r = c.post(URL, json={"pending_order_id": p["pending_order_id"], "user_confirmed": True})
    assert r.status_code == 503 and r.json()["error"]["code"] == "payment_unavailable" and "secret-host" not in r.text
    ok = c.post(URL, json={"pending_order_id": p["pending_order_id"], "user_confirmed": True})
    assert ok.status_code == 200 and len(fake.orders["ORD1"]["purchase_units"][0]["payments"]["captures"]) == 1
