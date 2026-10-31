"""Elastic Serverless client, index mappings and ElasticCatalogProvider (spec 7.1).
API shapes verified against elastic.co/docs on 2026-10-31: `rrf` retriever with a top-level
`filter` (applied to every child retriever), `knn` retriever, `POST /_inference/text_embedding/{id}`,
`POST /_bulk` (NDJSON). Serverless: no shard/replica settings; connect by project endpoint URL + ApiKey."""
import datetime as dt
import json
import os
from decimal import Decimal

from catalog.providers._http import request_json
from catalog.providers.base import Product, Review

EMBED_ID = ".jina-embeddings-v5-text-nano"  # EIS-hosted, no cold start (e5-small deployment timed out, HTTP 408, live)
DIMS = 768  # verified live 2026-10-31


def _vec(dims=DIMS):
    return {"type": "dense_vector", "dims": dims, "index": True, "similarity": "cosine"}


def mappings(dims: int = DIMS) -> dict[str, dict]:
    kw, dte = {"type": "keyword"}, {"type": "date"}
    return {
        "products": {"properties": {
            "product_id": kw, "title": {"type": "text"}, "brand": kw, "category": kw,
            "price": {"type": "scaled_float", "scaling_factor": 100}, "currency": kw,
            "variants": {"type": "flattened"}, "attributes": {"type": "flattened"},
            "merchant_url": {"type": "keyword", "index": False}, "image_url": {"type": "keyword", "index": False},
            "rating_average": {"type": "float"}, "rating_count": {"type": "integer"},
            "reviews_indexed": {"type": "integer"},  # real reviews held in `reviews`; 0 = reviews: none
            "source": kw, "as_of": dte, "embedding": _vec(dims)}},
        "reviews": {"properties": {
            "review_id": kw, "product_id": kw, "rating": {"type": "float"}, "title": {"type": "text"},
            "text": {"type": "text"}, "date": dte, "helpful_votes": {"type": "integer"},
            "verified": {"type": "boolean"}, "reviewer_context": {"type": "flattened"},
            "source": kw, "as_of": dte, "embedding": _vec(dims)}},
        "traces": {"properties": {
            "episode_id": kw, "task_id": kw, "agent_id": kw, "generation": {"type": "integer"},
            "kill_reason": kw, "killed": {"type": "boolean"}, "fitness": {"type": "float"},
            "category": kw, "split": kw, "created_at": dte,
            "episode": {"type": "object", "enabled": False}}},  # full episode JSON, not indexed
        "kill_rules": {"properties": {
            "rule_id": kw, "version": {"type": "integer"}, "description": {"type": "text"},
            "added_at": dte, "kills": {"type": "integer"}}},
        "generations": {"properties": {
            "gen_id": kw, "generation": {"type": "integer"}, "status": kw, "population_size": {"type": "integer"},
            "survivors": {"type": "integer"}, "kills": {"type": "integer"},
            "started_at": dte, "finished_at": dte, "config": {"type": "flattened"}}},
    }


class Elastic:
    """Minimal REST client. `url` is the Serverless project endpoint (not the Cloud ID)."""

    def __init__(self, url: str | None = None, api_key: str | None = None, prefix: str = "", transport=request_json):
        self.url = (url or os.environ["ELASTIC_ENDPOINT"]).rstrip("/")
        self.key = api_key or os.environ["ELASTIC_API_KEY"]
        self.prefix, self.transport = prefix, transport

    def ix(self, name: str) -> str:
        return self.prefix + name

    def call(self, method, path, body=None, ndjson=False):
        h = {"Authorization": f"ApiKey {self.key}",
             "Content-Type": "application/x-ndjson" if ndjson else "application/json"}
        return self.transport(method, self.url + path, h, body)

    def ensure_indices(self, dims: int = DIMS):
        for name, m in mappings(dims).items():
            try:
                self.call("PUT", f"/{self.ix(name)}", {"mappings": m})
            except Exception as e:  # already exists is fine, anything else is not
                if "resource_already_exists" not in str(e):
                    raise

    def bulk(self, index: str, docs: list[tuple[str, dict]]) -> int:
        """Index (id, doc) pairs idempotently (same id overwrites). Raises on any item error."""
        lines = []
        for _id, doc in docs:
            lines += [json.dumps({"index": {"_index": self.ix(index), "_id": _id}}), json.dumps(doc, default=str)]
        out = self.call("POST", "/_bulk?refresh=wait_for", "\n".join(lines) + "\n", ndjson=True)
        if out.get("errors"):
            bad = [i["index"]["error"] for i in out["items"] if "error" in i["index"]]
            raise RuntimeError(f"bulk errors ({len(bad)}): {bad[0]}")
        return len(docs)

    def embed(self, texts: list[str], inference_id: str = EMBED_ID, input_type="ingest"):
        out = self.call("POST", f"/_inference/text_embedding/{inference_id}",
                        {"input": texts, "input_type": input_type})
        return [e["embedding"] for e in out["text_embedding"]]


def hybrid_review_query(product_id: str, text: str, vector: list[float], size: int = 10, window: int = 50) -> dict:
    """Keyword + vector (RRF), scoped to one product: the top-level rrf `filter` applies to both children."""
    return {
        "size": size,
        "_source": {"excludes": ["embedding"]},
        "retriever": {"rrf": {
            "retrievers": [
                {"standard": {"query": {"multi_match": {"query": text, "fields": ["title^2", "text"]}}}},
                {"knn": {"field": "embedding", "query_vector": vector, "k": window, "num_candidates": window * 2}},
            ],
            "filter": {"term": {"product_id": product_id}},
            "rank_window_size": window,
        }},
    }


def _product(src: dict) -> Product:
    return Product(
        id=src["product_id"], title=src["title"], brand=src.get("brand"), category=src["category"],
        price=Decimal(str(src["price"])), currency=src.get("currency", "USD"),
        variants=src.get("variants") or {}, attributes=src.get("attributes") or {},
        source=src["source"], as_of=dt.datetime.fromisoformat(src["as_of"]))


def _review(src: dict) -> Review:
    return Review(
        id=src["review_id"], product_id=src["product_id"], rating=src["rating"], text=src["text"],
        date=dt.date.fromisoformat(src["date"][:10]) if src.get("date") else None,
        helpful_votes=src.get("helpful_votes", 0), verified=src.get("verified", False),
        reviewer_context=src.get("reviewer_context") or {})


class ElasticCatalogProvider:
    """Snapshot provider: every result carries the doc's own source + as_of (the frozen snapshot time)."""

    def __init__(self, es: Elastic, embed=None):
        self.es = es
        self.embed = embed or (lambda t: es.embed([t], input_type="search")[0])

    def search(self, query: str, filters: dict | None = None, size: int = 10) -> list[Product]:
        f = filters or {}
        flt = [{"term": {"category": f["category"]}}] if f.get("category") else []
        if f.get("max_price") is not None or f.get("min_price") is not None:
            flt.append({"range": {"price": {op: f[k] for k, op in (("min_price", "gte"), ("max_price", "lte")) if f.get(k) is not None}}})
        body = {"size": size, "_source": {"excludes": ["embedding"]},
                "query": {"bool": {"must": [{"match": {"title": query}}], "filter": flt}}}
        hits = self.es.call("POST", f"/{self.es.ix('products')}/_search", body)["hits"]["hits"]
        return [_product(h["_source"]) for h in hits]

    def get_product(self, product_id: str) -> Product | None:
        body = {"size": 1, "_source": {"excludes": ["embedding"]}, "query": {"term": {"product_id": product_id}}}
        hits = self.es.call("POST", f"/{self.es.ix('products')}/_search", body)["hits"]["hits"]
        return _product(hits[0]["_source"]) if hits else None

    def get_reviews(self, product_id: str, focus: str | None = None, limit: int = 10) -> list[Review]:
        idx = f"/{self.es.ix('reviews')}/_search"
        if focus:
            body = hybrid_review_query(product_id, focus, self.embed(focus), size=limit)
        else:
            body = {"size": limit, "_source": {"excludes": ["embedding"]}, "query": {"term": {"product_id": product_id}}}
        return [_review(h["_source"]) for h in self.es.call("POST", idx, body)["hits"]["hits"]]


def endpoint_from_cloud_id(cloud_id: str) -> str:
    """Best-effort `https://{es}.{host}` from a Cloud ID. Serverless projects publish their own endpoint URL
    (ELASTIC_ENDPOINT); this fallback is only a guess when that is missing."""
    import base64
    raw = cloud_id.split(":", 1)[-1]
    host, es, *_ = base64.b64decode(raw + "=" * (-len(raw) % 4)).decode().split("$")
    return f"https://{es}.{host}"
