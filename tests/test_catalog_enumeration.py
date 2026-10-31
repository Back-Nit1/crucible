"""Snapshot enumeration and complete review-id lookup, against a fake Elastic that honours search_after paging."""
import pytest

from catalog.providers.elastic import Elastic, ElasticCatalogProvider


class FakeEs:
    """Serves _search with sort + search_after + size; a request whose size exceeds 10,000 mimics the real window cap."""

    def __init__(self, products=(), reviews=()):
        self.data = {"products": list(products), "reviews": list(reviews)}
        self.requests = []

    def __call__(self, method, url, headers, body=None):
        idx = url.rsplit("/", 2)[-2]
        self.requests.append((url, body))
        if url.endswith("/_count"):
            term = body["query"]["term"]
            (k, v), = term.items()
            return {"count": sum(d[k] == v for d in self.data[idx])}
        assert body["size"] <= 10_000, "result window exceeded"
        (field, _), = [(list(s)[0], 0) for s in body["sort"]]
        docs = self.data[idx]
        (k, v), = body["query"]["term"].items()
        docs = sorted((d for d in docs if d[k] == v), key=lambda d: d[field])
        if "search_after" in body:
            docs = [d for d in docs if d[field] > body["search_after"][0]]
        page = docs[: body["size"]]
        inc = (body.get("_source") or {}).get("includes")
        return {"hits": {"hits": [{"_source": {f: d[f] for f in inc} if inc else d, "sort": [d[field]]} for d in page]}}


def prod(i, cat="shoes"):
    return {"product_id": f"P{i:05d}", "title": "t", "category": cat, "price": 10, "source": "amazon2023",
            "as_of": "2023-09-30T00:00:00+00:00"}


def rev(i, pid="P00001"):
    return {"review_id": f"amazon2023:{pid}:{i:06d}", "product_id": pid, "rating": 4.0, "text": "x",
            "source_review_key": f"{pid}:{i}"}


def provider(**kw):
    t = FakeEs(**kw)
    return ElasticCatalogProvider(Elastic("https://x", "k", transport=t)), t


def test_iter_products_is_complete_sorted_and_category_scoped():
    p, t = provider(products=[prod(i) for i in range(1200, 0, -1)] + [prod(9999, "other")])
    got = list(p.iter_products("shoes"))
    assert [x.id for x in got] == [f"P{i:05d}" for i in range(1, 1201)]
    assert len(t.requests) == 3  # 500 + 500 + 200: paged, not one capped request


def test_review_ids_do_not_truncate_at_10000():
    p, _ = provider(reviews=[rev(i) for i in range(25_000)] + [rev(0, "P00002")])
    ids = p.review_ids("P00001")
    assert len(ids) == 25_000 and p.review_count("P00001") == 25_000
    assert all(i.startswith("amazon2023:P00001:") for i in ids)  # product-scoped


def test_get_reviews_without_focus_honours_limits_above_the_window():
    p, _ = provider(reviews=[rev(i) for i in range(12_000)])
    assert len(p.get_reviews("P00001", limit=11_000)) == 11_000
    assert len(p.get_reviews("P00001", limit=10)) == 10
    assert p.get_reviews("P00001", limit=10)[0].source_id == "P00001:0"  # original id preserved separately


def test_review_ids_refuse_ambiguous_duplicates():
    p, _ = provider(reviews=[rev(1), rev(1)])
    with pytest.raises(RuntimeError, match="duplicate review ids"):
        p.review_ids("P00001")


def test_empty_query_is_not_enumeration():
    p, _ = provider()
    with pytest.raises(ValueError, match="iter_products"):
        p.search("", {"category": "shoes"})
