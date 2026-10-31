import json

import pytest

from catalog.providers.elastic import DIMS, Elastic, ElasticCatalogProvider, hybrid_review_query, mappings

REVIEW_SRC = {"review_id": "r1", "product_id": "P1", "rating": 2.0, "text": "flat after 150 miles",
              "date": "2020-12-17T00:00:00", "helpful_votes": 3, "verified": True}
PRODUCT_SRC = {"product_id": "P1", "title": "Shoe", "category": "shoes", "price": 99.99,
               "source": "amazon2023", "as_of": "2023-09-01T00:00:00+00:00"}


class Rec:
    def __init__(self, resp=None):
        self.calls, self.resp = [], resp or {}

    def __call__(self, method, url, headers, body=None):
        self.calls.append((method, url, headers, body))
        return self.resp


def test_mappings_cover_spec_indices_and_vectors():
    m = mappings()
    assert set(m) == {"products", "reviews", "traces", "kill_rules", "generations"}
    assert m["reviews"]["properties"]["embedding"]["dims"] == DIMS
    assert m["reviews"]["properties"]["product_id"] == {"type": "keyword"}
    assert "number_of_shards" not in json.dumps(m)  # serverless rejects shard settings


def test_hybrid_query_is_rrf_scoped_by_product():
    q = hybrid_review_query("P1", "flat midsole", [0.1] * 3)["retriever"]["rrf"]
    assert q["filter"] == {"term": {"product_id": "P1"}}
    kinds = [list(r)[0] for r in q["retrievers"]]
    assert kinds == ["standard", "knn"]


def test_provider_scopes_reviews_keeps_ids_and_provenance():
    t = Rec({"hits": {"hits": [{"_source": REVIEW_SRC}]}})
    p = ElasticCatalogProvider(Elastic("https://x/", "k", transport=t), embed=lambda s: [0.0] * 3)
    r = p.get_reviews("P1", focus="durability", limit=5)[0]
    assert (r.id, r.product_id) == ("r1", "P1")
    method, url, headers, body = t.calls[0]
    assert url == "https://x/reviews/_search" and headers["Authorization"] == "ApiKey k"
    assert body["retriever"]["rrf"]["filter"] == {"term": {"product_id": "P1"}}
    t.resp = {"hits": {"hits": [{"_source": PRODUCT_SRC}]}}
    prod = p.get_product("P1")
    assert (prod.source, prod.as_of.year) == ("amazon2023", 2023)


def test_search_builds_price_range_filter():
    t = Rec({"hits": {"hits": []}})
    ElasticCatalogProvider(Elastic("https://x", "k", transport=t)).search("shoe", {"max_price": 100, "category": "shoes"})
    flt = t.calls[0][3]["query"]["bool"]["filter"]
    assert {"range": {"price": {"lte": 100}}} in flt and {"term": {"category": "shoes"}} in flt


def test_bulk_is_ndjson_with_stable_ids_and_raises_on_item_errors():
    t = Rec({"errors": False, "items": []})
    es = Elastic("https://x", "k", prefix="spike_", transport=t)
    assert es.bulk("reviews", [("r1", {"a": 1})]) == 1
    body = t.calls[0][3]
    assert json.loads(body.splitlines()[0]) == {"index": {"_index": "spike_reviews", "_id": "r1"}}
    t.resp = {"errors": True, "items": [{"index": {"error": {"type": "mapper_parsing_exception"}}}]}
    with pytest.raises(RuntimeError, match="mapper_parsing"):
        es.bulk("reviews", [("r1", {"a": 1})])


def test_endpoint_from_cloud_id():
    import base64
    from catalog.providers.elastic import endpoint_from_cloud_id
    cid = "n:" + base64.b64encode(b"us-east4.gcp.elastic.cloud$abc.es$abc.kb").decode()
    assert endpoint_from_cloud_id(cid) == "https://abc.es.us-east4.gcp.elastic.cloud"


def test_decimal_price_filters_serialize_on_the_wire():
    import json
    from decimal import Decimal
    from catalog.providers import _http
    seen = {}

    class R:
        def read(self): return b"{}"
        def __enter__(self): return self
        def __exit__(self, *a): pass
    def opener(req, timeout): seen["body"] = req.data; return R()
    orig = _http.urllib.request.urlopen
    _http.urllib.request.urlopen = opener
    try:
        _http.request_json("POST", "http://x", {}, {"range": {"price": {"lte": Decimal("25.50")}}})
    finally:
        _http.urllib.request.urlopen = orig
    assert json.loads(seen["body"]) == {"range": {"price": {"lte": 25.5}}}
