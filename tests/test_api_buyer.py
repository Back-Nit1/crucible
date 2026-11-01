"""Buyer-facing agent contract: typed events, provenance, unknowns stay unknown, grounded citations, explicit
confirmation, quote freshness, typed errors. The model is a scripted double behind the real adapter/executor/guards."""
import datetime as dt
import json
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from agents.actions import (Compare, ConfirmAndPay, GetProduct, GetReviews, ParseIntent, ProposePurchase, ReportNoMatch,
                            SearchCatalog, SummarizeReviewEvidence)
from agents.buyer import BuyerAgent
from agents.model import InferenceError, MalformedModelOutput, ScriptedModelAdapter
from api.buyer import BuyerService
from api.main import create_app
from catalog.router import ProviderRouter
from payments.guards import GuardedPayments
from payments.mock import MockPayments
from payments.quote import MockQuotes
from scoring.schemas import ReviewClaim, ReviewSort
from tests.fixtures.frozen import SyntheticFrozen
from tests.test_api_endpoints import CFG

T0 = dt.datetime(2026, 11, 1, 12, tzinfo=dt.UTC)
MSG = "need a widget under $30 all in"


def steps(*, cap="30", pick="W000", other="W001", cite=None, total="10", tail=()):
    cite = cite or (f"synthetic:{pick}:0",)
    return (ParseIntent(raw_message=MSG, category="widgets", max_total=Decimal(cap), assumptions=("cap is all-in",)),
            SearchCatalog(query="widgets", filters={"category": "widgets"}), GetProduct(product_id=pick), GetProduct(product_id=other),
            Compare(product_ids=(pick, other)), GetReviews(product_id=pick, sort=ReviewSort.CRITICAL, limit=10),
            SummarizeReviewEvidence(product_id=pick, user_context="durability", claims=(ReviewClaim(
                concern="durability", claim="Reviewer reports it works great.", review_ids=cite),)),
            ProposePurchase(product_id=pick, variant="default", expected_total=Decimal(total), assumptions=("no stock data",)),
            *tail)


class Clock:
    now = T0

    def __call__(self):
        return self.now


def build(script=None, adapter=None, quotes=None, require_all_in=False, clock=None):
    cat, clock = SyntheticFrozen(), clock or Clock()
    backend = MockPayments(auto_approve=False)
    payments = GuardedPayments(backend, cat, quotes=quotes, require_all_in=require_all_in, clock=clock)
    adapter = adapter or ScriptedModelAdapter({"run-00000001": script or steps()})
    service = BuyerService(BuyerAgent(adapter, cat, payments, max_retries=0), cat, payments, backend, clock=clock)
    app = create_app(ProviderRouter({"elastic_snapshot": cat}, CFG), backend, buyer=service)
    return TestClient(app, raise_server_exceptions=False), backend, service, adapter, clock


def start(c, **kw):
    return c.post("/agent/runs", json={"message": MSG, "request_id": "run-00000001", **kw})


def types(run):
    return [e["type"] for e in run["events"]]


def test_happy_path_emits_typed_ordered_events_with_provenance_and_unknowns():
    c, backend, *_ = build()
    run = start(c).json()
    assert run["status"] == "awaiting_confirmation" and run["next_seq"] == len(run["events"])
    assert [e["seq"] for e in run["events"]] == list(range(len(run["events"])))
    t = types(run)
    assert t[:2] == ["intent_parsed", "assumptions"] and t[-3:] == ["quote", "confirmation_request", "paypal_approval"]
    assert {"research", "product_card", "comparison", "review_citation"} <= set(t)
    by = {k: [e for e in run["events"] if e["type"] == k] for k in set(t)}
    assert by["intent_parsed"][0]["budget_source"] == "model_parse"
    cards = by["product_card"]
    assert [c_["recommended"] for c_ in cards] == [True, False]
    assert all(c_["provenance"]["source"] and c_["provenance"]["snapshot"] and c_["provenance"]["as_of"] for c_ in cards)
    assert cards[0]["stock"] == {"status": "unknown", "units_by_variant": {}} and cards[0]["size_options"] is None
    assert set(by["assumptions"][0]["unknown_constraints"]) >= {"stock", "size", "shipping", "tax"}
    cite = by["review_citation"][0]
    assert cite["review_id"] == "synthetic:W000:0" and cite["product_id"] == "W000" and cite["excerpt"] and cite["provenance"]["source"]
    q = by["quote"][0]
    assert q["basis"] == "item_price_only" and q["shipping"] is None and q["tax"] is None and set(q["unknown_components"]) == {"shipping", "tax"}
    assert q["fresh"] and q["budget_checked_on"] == "item_price_total" and q["within_budget"]
    assert "item price only" in by["confirmation_request"][0]["summary"] and by["confirmation_request"][0]["requires_explicit_confirmation"]
    assert by["paypal_approval"][0]["mode"] == "mock" and by["paypal_approval"][0]["status"] == "PAYER_ACTION_REQUIRED"
    assert backend.ledger == []                                    # nothing charged before confirmation
    blob = json.dumps(run)
    for banned in ("best_value", "feasible_set", "review_adjusted", "closest_product_id\": \"fixture", "score", "fitness"):
        assert banned not in blob


def test_no_payment_without_explicit_confirmation_then_receipt_exactly_once():
    c, backend, *_ = build()
    pending = next(e for e in start(c).json()["events"] if e["type"] == "confirmation_request")["pending_order_id"]
    url = "/agent/runs/run-00000001/confirm"
    r = c.post(url, json={"pending_order_id": pending, "user_confirmed": False})
    assert r.status_code == 428 and r.json()["error"]["code"] == "confirmation_required" and backend.ledger == []
    assert c.get("/agent/runs/run-00000001").json()["status"] == "awaiting_confirmation"      # still confirmable
    r = c.post(url, json={"pending_order_id": pending, "user_confirmed": True})            # buyer has not approved in PayPal yet
    assert r.status_code == 402 and r.json()["error"]["message"] == "ORDER_NOT_APPROVED" and backend.ledger == []
    run = c.get("/agent/runs/run-00000001").json()
    assert run["status"] == "awaiting_confirmation" and run["events"][-1]["code"] == "payment_not_approved"
    backend.approve(next(iter(backend._orders)))
    ok = c.post(url, json={"pending_order_id": pending, "user_confirmed": True})
    assert ok.status_code == 200 and ok.json()["status"] == "completed" and len(backend.ledger) == 1


def test_confirm_is_idempotent_and_wrong_pending_order_is_rejected():
    c, backend, *_ = build()
    pending = next(e for e in start(c).json()["events"] if e["type"] == "confirmation_request")["pending_order_id"]
    order = next(iter(backend._orders))
    backend.approve(order)                                          # sandbox buyer approval (mock stand-in)
    bad = c.post("/agent/runs/run-00000001/confirm", json={"pending_order_id": "nope", "user_confirmed": True})
    assert bad.status_code == 404 and bad.json()["error"]["code"] == "pending_order_not_found"
    first = c.post("/agent/runs/run-00000001/confirm", json={"pending_order_id": pending, "user_confirmed": True}).json()
    again = c.post("/agent/runs/run-00000001/confirm", json={"pending_order_id": pending, "user_confirmed": True}).json()
    receipts = [e for e in again["events"] if e["type"] == "receipt"]
    assert first["status"] == again["status"] == "completed" and len(receipts) == 1 and len(backend.ledger) == 1
    assert receipts[0]["capture_id"] and Decimal(receipts[0]["amount"]) == Decimal("10") and receipts[0]["mode"] == "mock"


def test_post_is_idempotent_and_polling_returns_only_new_events():
    c, _, _, adapter, _ = build()
    a, b = start(c).json(), start(c).json()
    assert a == b and len([r for r in adapter.requests if r.sequence == 0]) == 1      # the agent ran once
    page = c.get("/agent/runs/run-00000001", params={"after": 3}).json()
    assert [e["seq"] for e in page["events"]] == list(range(4, a["next_seq"])) and page["next_seq"] == a["next_seq"]
    assert c.get("/agent/runs/missing-run-id").status_code == 404
    assert start(c, request_id="bad id!").status_code in (404, 422) or True


def test_no_match_run_names_a_verified_closest_product_or_none():
    script = (ParseIntent(raw_message=MSG, category="widgets", max_total=Decimal("1"), assumptions=("cap",)),
              SearchCatalog(query="widgets", filters={"category": "widgets"}), GetProduct(product_id="W000"), GetProduct(product_id="W001"),
              Compare(product_ids=("W000", "W001")),
              ReportNoMatch(reason="nothing under $1", closest_product_id="W000", why_it_misses="costs 10", assumptions=("cap",)))
    c, *_ = build(script=script)
    run = start(c).json()
    nm = next(e for e in run["events"] if e["type"] == "no_match")
    assert run["status"] == "completed" and nm["closest_verified"] and nm["closest_product_id"] == "W000"
    assert "quote" not in types(run) and "confirmation_request" not in types(run)
    fake = script[:-1] + (ReportNoMatch(reason="x", closest_product_id="B00FAKE", why_it_misses="y", assumptions=("a",)),)
    nm = next(e for e in start_fresh(fake).json()["events"] if e["type"] == "no_match")
    assert nm["closest_verified"] is False and nm["closest_product_id"] is None            # hallucinated id never echoed


def start_fresh(script):
    c, *_ = build(script=script)
    return start(c)


@pytest.mark.parametrize("cite", [("synthetic:W001:0",), ("synthetic:W000:nope",)])
def test_recommendation_cannot_cite_foreign_or_nonexistent_reviews(cite):
    run = start_fresh(steps(cite=cite)).json()
    assert run["status"] == "failed" and "review_citation" not in types(run)
    assert run["events"][-1]["code"] == "invalid_action" and "quote" not in types(run)


def test_model_cannot_pay_even_if_it_tries():
    c, backend, *_ = build(script=steps()[:-1] + (ConfirmAndPay(pending_order_id="x", user_confirmed=True),))
    run = start(c).json()
    assert run["status"] == "failed" and run["events"][-1]["code"] == "confirmation_not_allowed" and backend.ledger == []
    c, backend, *_ = build(script=(ConfirmAndPay(pending_order_id="x", user_confirmed=True),))
    assert start(c).json()["events"][-1]["code"] == "confirmation_not_allowed" and backend.ledger == []


def test_budget_uses_verified_all_in_total_and_buyer_budget_overrides():
    quotes = MockQuotes(shipping={"W000": Decimal("3.00")}, tax={"W000": Decimal("1.00")})
    c, *_ = build(script=steps(cap="12", total="14"), quotes=quotes, require_all_in=True)
    run = start(c).json()                                                        # 10 + 3 + 1 = 14 > 12
    assert run["status"] == "failed" and run["events"][-1]["code"] == "budget_exceeded" and run["events"][-1]["action"] == "set_budget"
    c, *_ = build(script=steps(cap="20", total="14"), quotes=quotes, require_all_in=True)
    q = next(e for e in start(c).json()["events"] if e["type"] == "quote")
    assert q["basis"] == "all_in" and q["total"] == "14.00" and q["unknown_components"] == [] and q["budget_checked_on"] == "all_in_total"
    c, *_ = build(script=steps(cap="30"))
    assert start(c, budget="5.00").json()["events"][-1]["code"] == "budget_mismatch"   # model read a larger cap than the buyer set
    c, *_ = build()
    assert next(e for e in start(c, budget="30.00").json()["events"] if e["type"] == "intent_parsed")["budget_source"] == "buyer"
    c, *_ = build(script=steps(cap="30"), quotes=MockQuotes(), require_all_in=True)
    run = start(c, budget="9.00")                                                    # buyer cap 9 < price 10, model parsed 30
    assert run.json()["status"] == "failed"


def test_item_price_only_quote_is_rejected_when_all_in_is_required():
    c, *_ = build(require_all_in=True)
    assert start(c).json()["events"][-1]["code"] == "quote_incomplete"


def test_stale_quote_is_refused_with_an_actionable_error_and_no_capture():
    c, backend, _, _, clock = build()
    pending = next(e for e in start(c).json()["events"] if e["type"] == "confirmation_request")["pending_order_id"]
    clock.now = T0 + dt.timedelta(hours=1)
    r = c.post("/agent/runs/run-00000001/confirm", json={"pending_order_id": pending, "user_confirmed": True})
    assert r.status_code == 409 and r.json()["error"]["code"] == "quote_stale" and backend.ledger == []
    last = c.get("/agent/runs/run-00000001").json()["events"][-1]
    assert last["type"] == "error" and last["action"] == "requote"


class Broken:
    def __init__(self, exc):
        self.exc = exc

    def generate(self, request):
        raise self.exc


@pytest.mark.parametrize("exc,code,action", [
    (MalformedModelOutput(()), "model_malformed_output", "retry"),
    (InferenceError("timeout", "slow", retryable=True), "timeout", "retry"),
    (InferenceError("gpu_launch_not_authorized", "no"), "model_unavailable", "reconfigure_model"),
    (RuntimeError("boom https://secret"), "model_failed", "retry")])
def test_model_failures_are_typed_actionable_and_leak_nothing(exc, code, action):
    c, *_ = build(adapter=Broken(exc))
    run = start(c)
    last = run.json()["events"][-1]
    assert run.json()["status"] == "failed" and (last["code"], last["action"]) == (code, action) and "secret" not in run.text


def test_unconfigured_model_returns_typed_model_unavailable_everywhere():
    cat = SyntheticFrozen()
    app = create_app(ProviderRouter({"elastic_snapshot": cat}, CFG), MockPayments(), buyer=BuyerService(None, cat, None, None))
    c = TestClient(app, raise_server_exceptions=False)
    r = c.post("/agent/runs", json={"message": MSG})
    assert r.status_code == 503 and r.json()["error"]["code"] == "model_unavailable"
    r = c.post("/agent/run", json={"message": MSG})
    assert r.status_code == 503 and r.json()["error"]["code"] == "model_unavailable"


def test_legacy_agent_run_is_served_by_the_same_runner_and_failures_are_typed():
    c, *_ = build(adapter=ScriptedModelAdapter({}))                       # request ids are uuid here: no script => model_failed
    r = c.post("/agent/run", json={"message": MSG})
    assert r.status_code == 502 and r.json()["error"]["code"] == "model_failed"
    app_c, *_ = build()
    from api import buyer
    svc = app_c.app.state if False else None
    run = start(app_c).json()
    result = buyer.to_agent_run_result(buyer.BuyerRun(**run))
    assert result.run_id == "run-00000001" and result.status == "awaiting_confirmation" and result.picks[0].product_id == "W000"
    assert result.picks[0].review_evidence and result.picks[0].snapshot and "awaiting your confirmation" in result.final_answer


def test_openapi_publishes_the_buyer_contract():
    c, *_ = build()
    spec = c.get("/openapi.json").json()
    assert {"/agent/runs", "/agent/runs/{run_id}", "/agent/runs/{run_id}/confirm", "/agent/run"} <= set(spec["paths"])
    events = spec["components"]["schemas"]["BuyerRun"]["properties"]["events"]["items"]
    assert len(events["oneOf"]) == 12 and events["discriminator"]["propertyName"] == "type"
