from catalog.indexing import canonical_review_id, join, legacy_to_canonical, product_doc, review_doc, review_id, sample_stats

M = {"parent_asin": "P1", "title": "Shoe", "price": 50, "rating_number": 9, "features": ["x"], "store": "Acme"}
R = {"rating": 2.0, "title": "t", "text": "flat", "asin": "C1", "parent_asin": "P1",
     "user_id": "U1", "timestamp": 1608186804795, "helpful_vote": 3, "verified_purchase": True}


def test_review_doc_keeps_original_ids_and_provenance():
    d = review_doc(R)
    assert d["source_review_id"] == review_id(R) == "P1:C1:U1:1608186804795"
    assert d["review_id"] == canonical_review_id("amazon2023", "P1", review_id(R)) == legacy_to_canonical(review_id(R))
    assert d["review_id"].startswith("amazon2023:P1:") and d["review_id"] != d["source_review_id"]
    assert d["product_id"] == "P1" and d["date"] == "2020-12-17" and d["source"] == "amazon2023" and d["as_of"]


def test_product_doc_drops_unpriced_and_invents_no_stock():
    assert product_doc({**M, "price": None}, "X", 0) is None
    d = product_doc(M, "Video_Games", 7)
    assert d["variants"] == {} and d["reviews_indexed"] == 7 and d["source"] == "amazon2023"


def test_join_and_stats():
    metas = [M, {**M, "parent_asin": "P2", "price": None}]
    revs = [R] * 5 + [{**R, "parent_asin": "P2"}, {**R, "parent_asin": "ORPHAN"}]
    assert sorted(join(metas, revs)) == ["P1", "P2"]
    s = sample_stats(metas, revs)
    assert (s["products"], s["reviews_joined"], s["sample>=min"], s["usable"]) == (2, 6, 1, 1)


def test_canonical_id_is_stable_distinct_per_product_and_splits_exact_duplicates():
    a = canonical_review_id("amazon2023", "P1", "x:y:z:1")
    assert a == canonical_review_id("amazon2023", "P1", "x:y:z:1")
    assert a != canonical_review_id("amazon2023", "P2", "x:y:z:1")  # same source id under another product
    assert a != canonical_review_id("other", "P1", "x:y:z:1")
    assert a != canonical_review_id("amazon2023", "P1", "x:y:z:1", occurrence=1)
