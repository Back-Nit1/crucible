"""Offline: write docs/api/openapi.json and sanitized buyer-contract samples (docs/api/samples/agent_*.json).
Samples come from the real API code path over the SYNTHETIC test catalog with a scripted model double, a mock payment
backend and a fixed clock, so they are deterministic and clearly not Amazon data or model output.
  uv run python -m scripts.export_buyer_samples"""
import datetime as dt
import json
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

OUT = Path("docs/api")


def main() -> None:
    from agents.model import InferenceError
    from api.main import create_app
    from catalog.router import ProviderRouter
    from payments.mock import MockPayments
    from tests.fixtures.frozen import SyntheticFrozen
    from tests.test_api_buyer import CFG, MSG, Clock, build, steps
    from agents.actions import ParseIntent, SearchCatalog, GetProduct, Compare, ReportNoMatch

    def record(name, client, method, path, body=None):
        r = client.request(method, path, json=body)
        doc = {"request": f"{method} {path}", "body_sent": body, "status": r.status_code, "response": r.json(),
               "note": "synthetic catalog + scripted model double + mock payments: shape sample only"}
        (OUT / "samples").mkdir(parents=True, exist_ok=True)
        (OUT / "samples" / f"{name}.json").write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
        return r.json()

    c, backend, *_ = build()
    run = record("agent_run_started", c, "POST", "/agent/runs", {"message": MSG, "request_id": "run-00000001"})
    pending = next(e for e in run["events"] if e["type"] == "confirmation_request")["pending_order_id"]
    record("agent_run_poll", c, "GET", "/agent/runs/run-00000001?after=5")
    record("agent_confirm_refused_no_confirmation", c, "POST", "/agent/runs/run-00000001/confirm",
           {"pending_order_id": pending, "user_confirmed": False})
    record("agent_confirm_not_approved", c, "POST", "/agent/runs/run-00000001/confirm", {"pending_order_id": pending, "user_confirmed": True})
    backend.approve(next(iter(backend._orders)))
    record("agent_run_receipt", c, "POST", "/agent/runs/run-00000001/confirm", {"pending_order_id": pending, "user_confirmed": True})
    nm = (ParseIntent(raw_message=MSG, category="widgets", max_total=Decimal("1"), assumptions=("cap is all-in",)),
          SearchCatalog(query="widgets", filters={"category": "widgets"}), GetProduct(product_id="W000"), GetProduct(product_id="W001"),
          Compare(product_ids=("W000", "W001")),
          ReportNoMatch(reason="nothing under $1", closest_product_id="W000", why_it_misses="costs 10", assumptions=("cap",)))
    c2, *_ = build(script=nm)
    record("agent_run_no_match", c2, "POST", "/agent/runs", {"message": MSG, "request_id": "run-00000001"})
    c3, *_, clock = build()
    run3 = c3.post("/agent/runs", json={"message": MSG, "request_id": "run-00000001"}).json()
    clock.now += dt.timedelta(hours=1)
    record("agent_confirm_stale_quote", c3, "POST", "/agent/runs/run-00000001/confirm",
           {"pending_order_id": next(e for e in run3["events"] if e["type"] == "confirmation_request")["pending_order_id"], "user_confirmed": True})
    cat = SyntheticFrozen()
    from api.buyer import BuyerService
    bare = TestClient(create_app(ProviderRouter({"elastic_snapshot": cat}, CFG), MockPayments(), buyer=BuyerService(None, cat, None, None)),
                      raise_server_exceptions=False)
    record("agent_model_unavailable", bare, "POST", "/agent/runs", {"message": MSG})
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "openapi.json").write_text(json.dumps(c.get("/openapi.json").json(), indent=2, sort_keys=True) + "\n")
    print("wrote", OUT / "openapi.json", "and", len(list((OUT / "samples").glob("agent_*.json"))), "agent samples")


if __name__ == "__main__":
    main()
