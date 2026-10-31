"""Frozen-snapshot contract: explicit enumeration + complete review ids, against a paging fake of Elastic _search."""
import pytest

from catalog.providers.base import IncompleteReviewIds, SnapshotMismatch
from catalog.providers.elastic import Elastic, ElasticCatalogProvider

SRC = {"source": "amazon2023", "as_of": "2023-09-30T00:00:00+00:00", "price": 10.0, "title": "t"}
HASH = "h" * 64


class FakeEs:
    """Serves `size`/`sort`/`search_after`/`term` like the real thing over in-memory docs."""

    def __init__(self, products, reviews, lie_total=0):
        self.docs = {"products": products, "reviews": reviews}
        self.lie, self.calls = lie_total, 0

    def __call__(self, method, url, headers, body=None):
        self.calls += 1
        index = url.rsplit("/", 2)[-2]
        (field, value), = body["query"]["term"].items()
        key = next(iter(body["sort"][0])) if "sort" in body else "product_id"
        rows = sorted((d for d in self.docs[index] if d[field] == value), key=lambda d: d[key])
        if "search_after" in body:
            rows = [d for d in rows if d[key] > body["search_after"][0]]
        page = rows[: body["size"]]
        total = len([d for d in self.docs[index] if d[field] == value]) - self.lie
        return {"hits": {"total": {"value": total}, "hits": [{"_source": d, "sort": [d[key]]} for d in page]}}


def prod(pid, cat="shoes"):
    return {**SRC, "product_id": pid, "category": cat}


def provider(products, reviews, **kw):
    return ElasticCatalogProvider(Elastic("https://x", "k", transport=FakeEs(products, reviews, **kw)),
                                  embed=lambda t: [0.0], manifests={"shoes": HASH})


def test_iter_products_is_ordered_complete_and_stamped_with_snapshot_provenance():
    ids = [f"P{i:04d}" for i in range(1203)]  # > one page, inserted in shuffled order
    p = provider([prod(i) for i in reversed(ids)] + [prod("OTHER", "hats")], [])
    got = list(p.iter_products("shoes", HASH))
    assert [x.id for x in got] == ids  # no hidden limit, product-id order, other category excluded
    assert all(x.snapshot and x.manifest_hash == HASH and x.source == "amazon2023" and x.source_product_id == x.id for x in got)


def test_iter_products_rejects_unknown_manifest_hash():
    with pytest.raises(SnapshotMismatch):
        list(provider([prod("P1")], []).iter_products("shoes", "0" * 64))
    with pytest.raises(SnapshotMismatch):
        list(provider([prod("P1", "hats")], []).iter_products("hats", HASH))  # category has no manifest


def test_amazon_products_never_expose_stock_or_size_even_if_a_doc_carries_it():
    p = provider([{**prod("P1"), "variants": {"12": 3}}], [])
    assert list(p.iter_products("shoes", HASH))[0].variants == {}


def rev(pid, i):
    return {"review_id": f"amazon2023:{pid}:{i:05d}", "product_id": pid}


def test_review_ids_complete_for_large_sets_and_scoped_to_the_product():
    mine = [rev("P1", i) for i in range(1201)]
    p = provider([prod("P1"), prod("P2")], mine + [rev("P2", i) for i in range(7)])
    got = p.get_review_ids("P1")
    assert got.product_found and got.ids == {r["review_id"] for r in mine}
    assert not any(i.startswith("amazon2023:P2:") for i in got.ids)


def test_missing_product_is_a_typed_result_and_product_without_reviews_is_empty_but_found():
    p = provider([prod("P1")], [rev("P9", 1)])
    assert p.get_review_ids("NOPE").product_found is False and p.get_review_ids("NOPE").ids == frozenset()
    empty = p.get_review_ids("P1")
    assert empty.product_found and empty.ids == frozenset()


def test_truncation_is_detected_not_returned():
    p = provider([prod("P1")], [rev("P1", i) for i in range(10)], lie_total=-3)  # index claims 13, pages yield 10
    with pytest.raises(IncompleteReviewIds):
        p.get_review_ids("P1")
