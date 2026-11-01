"""Contract tests for the world/model/ledger API + agent-run contract. Data: real EpisodeRecords from the engine's own runner."""
import datetime as dt
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from api.readers import InMemoryReader
from api.world import AgentRunRequest, AgentRunResult, PickOut, ReplayStep, ReviewEvidenceOut
from catalog.router import ProviderRouter
from memory.episodes import trace_from_episode
from payments.mock import MockPayments
from tests.fixtures.scoring import InMemoryCatalog
from tests.test_memory_episodes import GENOME, run
from tests.test_api_endpoints import CFG, Snap

GEN = {"gen_id": "g1", "status": "completed", "population_size": 3, "survivors": 2, "kills": 1, "runner": "local",
       "config": {"seed": 7, "tasks": 4, "catalog_hash": "abc"}, "summary": {"survivors": ["agent-1"], "episodes": {"expected": 4}}}


def traces():
    out = []
    for i, (agent, total) in enumerate([("agent-1", "89"), ("agent-2", "89"), ("agent-3", "120")]):
        task, ep = run(ep=f"ep-{i}", agent=agent, total=total)
        t = trace_from_episode(ep, task, GENOME.model_copy(update={"id": agent}))
        out.append(t.model_copy(update={"generation_id": "g1", "fitness": t.fitness - i * 0.1 if t.scored else 0.0}))
    return out


class FakeRunner:
    def run(self, req):
        now = dt.datetime(2026, 11, 1, tzinfo=dt.UTC)
        return AgentRunResult(
            parsed_intent={"category": "shoes", "max_total": "100.00"}, assumptions=["10,000-yard means 10K"],
            steps=[ReplayStep(sequence=0, tool="parse_intent", arguments={}, result_references=[], result_summary="ok",
                              error_code=None, timestamp=now)],
            picks=[PickOut(product_id="p1", title="Trail shoe", price=Decimal("80.00"), currency="USD", source="amazon2023",
                           as_of=now, snapshot=True, reason="fits the budget",
                           review_evidence=[ReviewEvidenceOut(claim="runs small", review_ids=["r1"], rating=2.0)])],
            final_answer="Recommend p1", model="fake", latency_ms=5)


@pytest.fixture
def client():
    reader = InMemoryReader(traces(), [GEN], {"evaluations": [{"id": "e1", "metric": "success_rate", "value": 0.5}]})
    app = create_app(ProviderRouter({"elastic_snapshot": Snap()}, CFG), MockPayments(), reader=reader, runner=FakeRunner())
    return TestClient(app, raise_server_exceptions=False)


def test_generations_list_and_detail(client):
    page = client.get("/world/generations").json()
    assert page["total"] == 1 and page["items"][0]["generation_id"] == "g1" and page["items"][0]["seed"] == 7
    assert client.get("/world/generations", params={"status": "failed"}).json()["total"] == 0
    d = client.get("/world/generations/g1").json()
    assert d["summary"]["survivors"] == ["agent-1"]
    r = client.get("/world/generations/nope")
    assert r.status_code == 404 and r.json()["error"]["code"] == "generation_not_found"


def test_episodes_paginate_filter_sort_and_detail_replay(client):
    p = client.get("/world/episodes", params={"limit": 2, "sort": "-fitness"}).json()
    assert p["total"] == 3 and len(p["items"]) == 2 and (p["offset"], p["limit"]) == (0, 2)
    assert p["items"][0]["fitness"] >= p["items"][1]["fitness"] or p["items"][1]["fitness"] is None
    page2 = client.get("/world/episodes", params={"limit": 2, "offset": 2}).json()
    assert len(page2["items"]) == 1
    assert client.get("/world/episodes", params={"killed": True}).json()["total"] == 1
    assert client.get("/world/episodes", params={"agent_id": "agent-2"}).json()["items"][0]["agent_id"] == "agent-2"
    assert client.get("/world/episodes", params={"kill_rule_id": "K003_BUDGET_VIOLATION"}).json()["total"] == 1
    assert client.get("/world/episodes", params={"sort": "evil; drop"}).status_code == 422
    assert client.get("/world/episodes", params={"limit": 500}).status_code == 422
    d = client.get("/world/episodes/ep-0").json()
    assert [s["sequence"] for s in d["replay"]] == list(range(8)) and d["replay"][0]["tool"] == "parse_intent"
    assert d["genome"]["id"] == "agent-1" and d["score_components"]["gate"] == 1 and d["catalog_hash"]
    killed = client.get("/world/episodes/ep-2").json()
    assert killed["kills"][0]["rule_id"] == "K003_BUDGET_VIOLATION" and killed["kills"][0]["evidence"]
    assert client.get("/world/episodes/missing").status_code == 404


def test_leaderboard_kills_rules_and_ledger(client):
    lb = client.get("/world/leaderboard", params={"generation_id": "g1"}).json()
    assert [r["rank"] for r in lb["items"]] == [1, 2, 3] and lb["items"][0]["survivor"] is True
    assert lb["items"][-1]["kill_rules"] == ["K003_BUDGET_VIOLATION"]
    k = client.get("/world/kills").json()
    assert k["total"] == 1 and k["items"][0]["rule_id"] == "K003_BUDGET_VIOLATION"
    assert client.get("/world/kills", params={"rule_id": "K001_HALLUCINATED_PRODUCT"}).json()["total"] == 0
    rules = {x["rule_id"]: x for x in client.get("/world/kill-rules").json()}
    assert set(rules) >= {"K001_HALLUCINATED_PRODUCT", "K008_REVIEW_GAMING"} and rules["K003_BUDGET_VIOLATION"]["kills"] == 1
    led = client.get("/payments/ledger").json()
    assert led["total"] == 4 and {r["mode"] for r in led["items"]} == {"mock"}  # captured + order_created per good episode; blocked attempt excluded


def test_model_documents_and_empty_stores_are_stable_pages(client):
    ev = client.get("/models/evaluations").json()
    assert ev["total"] == 1 and ev["items"][0] == {"id": "e1", "data": {"metric": "success_rate", "value": 0.5}}
    assert client.get("/models/checkpoints").json() == {"items": [], "total": 0, "offset": 0, "limit": 50}


def test_agent_run_contract_and_unconfigured_model_is_a_clear_503():
    r = TestClient(create_app(ProviderRouter({"elastic_snapshot": Snap()}, CFG), MockPayments(), reader=InMemoryReader(), runner=FakeRunner()))
    out = r.post("/agent/run", json={"message": "running shoes under $100"}).json()
    assert out["picks"][0]["snapshot"] is True and out["picks"][0]["review_evidence"][0]["review_ids"] == ["r1"]
    assert r.post("/agent/run", json={"message": ""}).status_code == 422
    bare = TestClient(create_app(ProviderRouter({"elastic_snapshot": Snap()}, CFG), MockPayments(), reader=InMemoryReader()), raise_server_exceptions=False)
    e = bare.post("/agent/run", json={"message": "hi"})
    assert e.status_code == 503 and e.json()["error"]["code"] == "model_unavailable"


def test_world_endpoints_without_elastic_config_return_503_not_a_stack_trace(monkeypatch):
    for k in ("ELASTIC_API_KEY", "ELASTIC_ENDPOINT", "ELASTIC_CLOUD_ID"):
        monkeypatch.delenv(k, raising=False)
    c = TestClient(create_app(ProviderRouter({"elastic_snapshot": Snap()}, CFG), MockPayments()), raise_server_exceptions=False)
    assert c.get("/health").status_code == 200
    r = c.get("/world/generations")
    assert r.status_code == 503 and r.json()["error"]["code"] == "world_data_unavailable"


def test_responses_never_contain_credentials_or_urls_with_tokens(client):
    blob = " ".join(client.get(p).text for p in ("/world/episodes/ep-0", "/world/episodes", "/payments/ledger", "/world/leaderboard"))
    for needle in ("ApiKey", "client_secret", "access_token", "approval", "PAYPAL_", "Traceback"):
        assert needle not in blob
