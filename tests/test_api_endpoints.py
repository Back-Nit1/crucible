import datetime as dt
from decimal import Decimal

from fastapi.testclient import TestClient

from api.main import create_app
from catalog.providers.base import Product, Review
from catalog.router import ProviderRouter
from payments.mock import MockPayments

T0 = dt.datetime(2023, 9, 1, tzinfo=dt.UTC)


class Snap:
    items = [Product(id="p1", title="Trail shoe", category="shoes", price=Decimal("80.00"), source="amazon2023", as_of=T0)]

    def search(self, q, filters=None): return self.items
    def get_product(self, pid): return next((p for p in self.items if p.id == pid), None)
    def get_reviews(self, pid, focus=None, limit=10):
        return [Review(id="r1", product_id="p1", rating=4, text="fine")] if pid == "p1" else []


CFG = {"live_chat": "elastic_snapshot", "providers": {"elastic_snapshot": {"enabled": True, "reviews_source": "amazon2023"}, "bestbuy": {"enabled": False}}}


def client(backend=None):
    return TestClient(create_app(ProviderRouter({"elastic_snapshot": Snap()}, CFG), backend or MockPayments(auto_approve=False)), raise_server_exceptions=False)


PROPOSE = dict(task_id="t", agent_id="a", product_id="p1", variant="", expected_total="80.00", budget_cap="100.00")


def test_search_labels_snapshot_and_source():
    j = client().get("/catalog/search", params={"q": "shoe", "max_price": "100"}).json()
    assert j["snapshot"] is True and j["source"] == "amazon2023" and j["as_of"].startswith("2023-09-01")


def test_provider_status_shows_bestbuy_disabled():
    assert client().get("/providers/status").json()["providers"]["bestbuy"]["enabled"] is False


def test_reviews_and_missing_product():
    c = client()
    assert c.get("/catalog/products/p1/reviews").json()["reviews_available"] is True
    assert c.get("/catalog/products/nope/reviews").json()["reviews_available"] is False
    r = c.get("/catalog/products/nope")
    assert r.status_code == 404 and r.json()["error"]["code"] == "product_not_found"


def test_validation_error_is_structured():
    r = client().get("/catalog/search")
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_request"


def test_over_budget_rejected_before_order():
    r = client().post("/purchase/propose", json=PROPOSE | {"budget_cap": "50.00"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "budget_exceeded"


def test_price_mismatch_rejected():
    r = client().post("/purchase/propose", json=PROPOSE | {"expected_total": "70.00"})
    assert r.json()["error"]["code"] == "price_mismatch"


def test_capture_needs_explicit_confirmation_then_approval():
    c = client()
    p = c.post("/purchase/propose", json=PROPOSE).json()
    assert p["status"] == "PAYER_ACTION_REQUIRED" and p["total"] == "80.00"
    r = c.post("/purchase/confirm", json={"pending_order_id": p["pending_order_id"], "user_confirmed": False})
    assert r.status_code == 428 and r.json()["error"]["code"] == "confirmation_required"
    r = c.post("/purchase/confirm", json={"pending_order_id": p["pending_order_id"], "user_confirmed": True})
    assert r.status_code == 402 and r.json()["error"]["code"] == "payment_failed"  # buyer has not approved


def test_confirm_after_approval_captures_exact_amount():
    be = MockPayments(auto_approve=False)
    c = client(be)
    p = c.post("/purchase/propose", json=PROPOSE).json()
    be.approve(next(iter(be._orders)))  # the only order created
    r = c.post("/purchase/confirm", json={"pending_order_id": p["pending_order_id"], "user_confirmed": True}).json()
    assert r["status"] == "COMPLETED" and r["amount"] == "80.00"


def test_unknown_pending_order_404_and_no_internal_leak():
    r = client().post("/purchase/confirm", json={"pending_order_id": "x", "user_confirmed": True})
    assert r.status_code == 404


def test_unhandled_error_hides_internals():
    class Boom(Snap):
        def search(self, q, filters=None): raise RuntimeError("secret-token-123")
    c = TestClient(create_app(ProviderRouter({"elastic_snapshot": Boom()}, CFG), MockPayments()), raise_server_exceptions=False)
    r = c.get("/catalog/search", params={"q": "x"})
    assert r.status_code == 500 and "secret-token-123" not in r.text


def test_propose_labels_the_quote_basis_and_never_claims_all_in_for_item_price():
    j = client().post("/purchase/propose", json=PROPOSE).json()
    assert j["quote_basis"] == "item_price_only" and j["quote_id"].startswith("q-") and j["total"] == "80.00"


def test_require_all_in_env_blocks_item_price_only_checkout(monkeypatch):
    monkeypatch.setenv("REQUIRE_ALL_IN_QUOTE", "1")
    r = client().post("/purchase/propose", json=PROPOSE)
    assert r.status_code == 409 and r.json()["error"]["code"] == "quote_incomplete"
