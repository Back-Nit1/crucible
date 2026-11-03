import datetime as dt
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from api.readers import ElasticReader
from catalog.router import ProviderRouter
from eval.comparison import ContenderRun
from eval.publish import EvaluationContext, checkpoint_doc, evaluation_docs, publish
from payments.mock import MockPayments
from tests.test_api_endpoints import CFG, Snap
from tests.test_memory_episodes import GENOME, run

NOW = dt.datetime(2026, 11, 1, tzinfo=dt.UTC)
CTX = EvaluationContext(model="Qwen/Qwen2.5-7B-Instruct", catalog_hash="c" * 64, prompt_version="shopper-prompts-v1",
                        judge_version="none", seed=7, created_at=NOW)


class FakeEs:
    """Records calls like the Elastic client; `search` replays what was bulk-indexed."""
    prefix = ""

    def __init__(self):
        self.docs, self.calls = {}, []

    def ix(self, name):
        return name

    def call(self, method, path, body=None, ndjson=False):
        self.calls.append((method, path))
        if method == "POST" and path.endswith("/_search"):
            index = path.strip("/").split("/")[0]
            hits = [{"_id": i, "_source": d} for i, d in self.docs.get(index, {}).items()]
            return {"hits": {"hits": hits, "total": {"value": len(hits)}}}
        return {}

    def bulk(self, index, docs):
        self.docs.setdefault(index, {}).update(dict(docs))
        return len(docs)


def runs():
    task, ep = run(ep="e1")
    _, ep2 = run(ep="e1", agent="agent-2")                     # same task + seed, different contender
    return task, (ContenderRun(contender_id="base-qwen", checkpoint="qwen-base", memory_enabled=False, episodes=(ep,)),
                  ContenderRun(contender_id="base-qwen-memory", checkpoint="qwen-base", memory_enabled=True, episodes=(ep2,)))


def test_evaluation_documents_declare_everything_needed_to_reproduce_and_compare():
    task, rs = runs()
    docs = dict(evaluation_docs(rs, {task.id: task}, CTX))
    assert len(docs) == 2
    d = next(iter(docs.values()))
    for key in ("evaluation_id", "model", "checkpoint", "split", "seed", "task_set_hash", "catalog_hash", "prompt_version",
                "judge_version", "latency_cost", "failure_counts", "held_out_category_performance", "lineage", "metrics"):
        assert key in d
    assert d["metrics"]["success_rate"]["denominator"] == "1" and d["failure_counts"]["episodes"] == 1
    assert d["latency_cost"]["denominator_episodes"] == 1 and d["split"] == task.split.value
    assert len({x["task_set_hash"] for x in docs.values()}) == 1                    # identical pairs => identical task set


def test_published_sample_matches_model_dashboard_contract():
    task, rs = runs()
    doc = next(iter(dict(evaluation_docs(rs, {task.id: task}, CTX)).values()))
    assert {"contender", "status", "seeds", "pass_at_k", "latency_ms", "cost_per_task_usd", "variance"} <= doc.keys()
    assert isinstance(doc["seeds"], list) and doc["status"] == "completed"
    for metric in doc["metrics"].values():
        assert {"numerator", "denominator", "excluded", "value"} <= metric.keys()
    assert doc["pass_at_k"] == doc["metrics"]["pass_at_k"]

    _, checkpoint = checkpoint_doc(checkpoint_id="qwen-base", base_model="Qwen/Qwen2.5-7B-Instruct",
                                   base_revision="a09a35458c702b33eeacc393d103063234e8bc28", created_at=NOW)
    assert {"status", "base_model", "manifest_hash", "catalog_hash"} <= checkpoint.keys()
    assert checkpoint["manifest_hash"] is None and checkpoint["catalog_hash"] is None


def test_mismatched_task_seed_pairs_cannot_be_published():
    task, (a, b) = runs()
    with pytest.raises(ValueError, match="identical task IDs and seeds"):
        evaluation_docs((a, b.model_copy(update={"episodes": (b.episodes[0].model_copy(update={"seed": 999}),)})), {task.id: task}, CTX)


def test_checkpoint_records_never_claim_training_that_did_not_happen():
    cid, base = checkpoint_doc(checkpoint_id="qwen-base", base_model="Qwen/Qwen2.5-7B-Instruct",
                               base_revision="a09a35458c702b33eeacc393d103063234e8bc28", created_at=NOW)
    assert base["status"] == "base" and base["lineage"]["chain"] == ["qwen-base"] and base["artifact_ref"] is None
    for bad in (dict(status="trained"), dict(status="planned"), dict(status="bogus"), dict(status="base", parent_checkpoint="x")):
        with pytest.raises(ValueError):
            checkpoint_doc(checkpoint_id="c", base_model="m", base_revision="r", created_at=NOW, **bad)


def test_published_records_come_back_through_the_model_endpoints():
    task, rs = runs()
    es = FakeEs()
    publish(es, "evaluations", evaluation_docs(rs, {task.id: task}, CTX))
    publish(es, "checkpoints", [checkpoint_doc(checkpoint_id="qwen-base", base_model="m", base_revision="r", created_at=NOW)])
    publish(es, "evaluations", evaluation_docs(rs, {task.id: task}, CTX))                  # idempotent upsert
    assert len(es.docs["evaluations"]) == 2 and ("PUT", "/evaluations") in es.calls
    c = TestClient(create_app(ProviderRouter({"elastic_snapshot": Snap()}, CFG), MockPayments(), reader=ElasticReader(es)),
                   raise_server_exceptions=False)
    ev = c.get("/models/evaluations").json()
    assert ev["total"] == 2 and ev["items"][0]["data"]["task_set_hash"] and ev["items"][0]["id"].startswith(("base-qwen", ))
    ck = c.get("/models/checkpoints").json()
    assert ck["total"] == 1 and ck["items"][0]["id"] == "qwen-base" and ck["items"][0]["data"]["status"] == "base"
