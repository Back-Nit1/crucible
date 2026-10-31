from catalog.indexing import join, legacy_to_canonical, source_review_key, product_doc, review_doc, review_id, sample_stats

M = {"parent_asin": "P1", "title": "Shoe", "price": 50, "rating_number": 9, "features": ["x"], "store": "Acme"}
R = {"rating": 2.0, "title": "t", "text": "flat", "asin": "C1", "parent_asin": "P1",
     "user_id": "U1", "timestamp": 1608186804795, "helpful_vote": 3, "verified_purchase": True}


def test_review_doc_keeps_original_ids_and_provenance():
    d = review_doc(R)
    assert d["source_review_key"] == source_review_key(R) == "P1:C1:U1:1608186804795"
    assert d["review_id"] == legacy_to_canonical(source_review_key(R)) == "amazon2023:P1:C1:U1:1608186804795"
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


def test_repeated_source_rows_get_distinct_stable_ids_and_the_same_content_hash():
    first, again = review_doc(R, 0), review_doc(R, 1)
    assert again["review_id"] == first["review_id"] + ":1" and again["source_ordinal"] == 1
    assert first["source_record_sha256"] == again["source_record_sha256"]  # provably the same source row
    assert review_doc({**R, "parent_asin": "P2"})["review_id"] != first["review_id"]  # product-scoped
