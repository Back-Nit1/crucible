import datetime as dt

from catalog.sources.snapshot import build, stream_jsonl


def meta(i, price=10.0, n=50):
    return {"parent_asin": f"P{i}", "title": f"t{i}", "price": price, "rating_number": n, "average_rating": 4.0}


def rev(p, k, text="good"):
    return {"parent_asin": p, "asin": p, "user_id": f"u{k}", "timestamp": 1_600_000_000_000 + k, "rating": 5.0, "text": text, "title": "x"}


def run(**kw):
    metas = [meta(1, n=90), meta(2, n=80), meta(3, price=None, n=70), meta(4, n=60)]
    revs = [rev("P1", k) for k in range(8)] + [rev("P2", k) for k in range(3)] + [rev("P3", k) for k in range(9)] + [rev("P9", 1)] + [rev("P1", 99, text="")]
    return build("Cat", iter(metas), iter(revs), now=dt.datetime(2026, 1, 1, tzinfo=dt.UTC), **kw)


def test_keeps_only_priced_products_with_enough_real_reviews():
    products, reviews, m = run(min_reviews=5)
    assert [p["product_id"] for p in products] == ["P1"]  # P2 thin, P3 unpriced, P4 no reviews
    assert len(reviews) == 8 and all(r["product_id"] == "P1" for r in reviews)  # empty-text review dropped
    assert (m["products"], m["reviews"], m["candidates"]) == (1, 8, 3)


def test_per_product_cap_and_provenance():
    _, reviews, m = run(min_reviews=5, per_product=6)
    assert len(reviews) == 6 and all(r["source"] == "amazon2023" and r["source_review_key"].startswith("P1:P1:") for r in reviews)
    assert m["sample_rule"]["per_product"] == 6 and m["review_records_scanned"] == 22


def test_deterministic_hash():
    assert run()[2]["sha256"] == run()[2]["sha256"] and run(per_product=6)[2]["sha256"] != run()[2]["sha256"]


def test_stream_jsonl_drops_partial_last_line():
    class R:
        def __init__(s): s.d = [b'{"a":1}\n{"a":2}\n{"a"', b""]
        def read(s, n): return s.d.pop(0) if s.d else b""
        def __enter__(s): return s
        def __exit__(s, *a): pass
    assert list(stream_jsonl("http://x", 10, opener=lambda req, timeout: R())) == [{"a": 1}, {"a": 2}]


def test_identical_source_reviews_get_distinct_canonical_ids_and_keep_the_original():
    metas = [meta(1, n=90)]
    revs = [rev("P1", 1)] * 6 + [rev("P1", 2)]  # byte-identical duplicates: the 17-collision pattern
    _, reviews, m = build("Cat", iter(metas), iter(revs), min_reviews=5)
    ids = [r["review_id"] for r in reviews]
    assert len(ids) == len(set(ids)) == 7 == m["reviews"]
    assert len({r["source_review_key"] for r in reviews}) == 2  # provenance still shows the shared source id
