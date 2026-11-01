"""Opt-in (`pytest -m live`): evaluation/checkpoint records round-trip through real Elastic and the API in a disposable prefix."""
import os
import uuid

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from api.readers import ElasticReader
from catalog.providers.elastic import Elastic, endpoint_from_cloud_id
from catalog.router import ProviderRouter
from eval.publish import checkpoint_doc, publish
from payments.mock import MockPayments
from tests.test_api_endpoints import CFG, Snap
from tests.test_eval_publish import NOW, CTX, evaluation_docs, runs

pytestmark = pytest.mark.live


def test_models_endpoints_return_real_elastic_records():
    url = os.environ.get("ELASTIC_ENDPOINT") or (endpoint_from_cloud_id(os.environ["ELASTIC_CLOUD_ID"]) if os.environ.get("ELASTIC_CLOUD_ID") else None)
    if not (url and os.environ.get("ELASTIC_API_KEY")):
        pytest.skip("no Elastic credentials")
    es = Elastic(url, prefix=f"crucible_livetest_{uuid.uuid4().hex[:8]}_")
    try:
        task, rs = runs()
        assert publish(es, "evaluations", evaluation_docs(rs, {task.id: task}, CTX)) == 2
        publish(es, "checkpoints", [checkpoint_doc(checkpoint_id="qwen-base", base_model="m", base_revision="r", created_at=NOW)])
        c = TestClient(create_app(ProviderRouter({"elastic_snapshot": Snap()}, CFG), MockPayments(), reader=ElasticReader(es)))
        ev, ck = c.get("/models/evaluations").json(), c.get("/models/checkpoints").json()
        assert ev["total"] == 2 and ev["items"][0]["data"]["catalog_hash"] == CTX.catalog_hash
        assert ck["total"] == 1 and ck["items"][0]["data"]["status"] == "base"
    finally:
        for name in ("evaluations", "checkpoints"):
            try:
                es.call("DELETE", f"/{es.ix(name)}")
            except Exception:
                pass
