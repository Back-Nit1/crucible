"""Opt-in (`pytest -m live`): real Elastic round trip in a disposable index prefix. Needs ELASTIC_* in the environment."""
import os
import uuid

import pytest

from catalog.providers.elastic import Elastic, endpoint_from_cloud_id
from memory.elastic import ElasticTraceRepository
from memory.episodes import RepositoryMemoryProvider, trace_from_episode
from agents.memory import RetrievalRequest
from tasks.schemas import TaskSplit
from tests.test_memory_episodes import GENOME, run

pytestmark = pytest.mark.live


def es_client(prefix):
    url = os.environ.get("ELASTIC_ENDPOINT") or (endpoint_from_cloud_id(os.environ["ELASTIC_CLOUD_ID"]) if os.environ.get("ELASTIC_CLOUD_ID") else None)
    if not (url and os.environ.get("ELASTIC_API_KEY")):
        pytest.skip("no Elastic credentials")
    return Elastic(url, prefix=prefix)


def test_traces_round_trip_and_leakage_filters_on_real_elastic():
    prefix = f"crucible_livetest_{uuid.uuid4().hex[:8]}_"
    es = es_client(prefix)
    try:
        es.ensure_indices()
        mem = RepositoryMemoryProvider(ElasticTraceRepository(es))
        good_task, good = run(ep="live-good")
        test_task, leaked = run(split=TaskSplit.TEST, ep="live-test")
        dead_task, dead = run(ep="live-dead", total="120")
        for task, ep in ((good_task, good), (test_task, leaked), (dead_task, dead)):
            mem.record(ep, task, GENOME, generation=1)  # dashboard path stores everything
        stored = es.call("POST", f"/{es.ix('traces')}/_count", {})["count"]
        assert stored == 3
        doc = es.call("POST", f"/{es.ix('traces')}/_search", {"query": {"term": {"episode_id": "live-good"}}})["hits"]["hits"][0]["_source"]
        assert doc["episode"]["tool_calls"][0]["action"]["type"] == "parse_intent" and doc["genome"]["id"] == GENOME.id
        got = mem.retrieve(RetrievalRequest("new", TaskSplit.TRAIN, "running-shoes", "running shoes under 100 cushioning", 3, 0.0))
        assert [e.episode_id for e in got] == ["live-good"]  # test-split and killed traces are never returned
        assert trace_from_episode(got[0], good_task).catalog_hash == good_task.catalog_manifest_hash
    finally:
        for name in ("products", "reviews", "traces", "kill_rules", "generations"):
            try:
                es.call("DELETE", f"/{es.ix(name)}")
            except Exception:
                pass
