from scripts.migrate_review_ids import legacy_record, migrate_docs


def legacy(key, text="same"):
    return {"review_id": key, "product_id": key.split(":")[0], "rating": 4.0, "title": "t", "text": text, "helpful_votes": 2,
            "verified": True, "source": "amazon2023", "as_of": "2023-09-30T00:00:00+00:00", "date": "2020-01-01", "reviewer_context": {}}


def test_identical_legacy_rows_become_two_distinct_ids_and_keep_the_original_key():
    plan = migrate_docs([legacy("P1:A:U:100"), legacy("P1:A:U:100"), legacy("P1:A:U:101")])
    ids = [d["review_id"] for _, d in plan]
    assert ids == ["amazon2023:P1:A:U:100", "amazon2023:P1:A:U:100:1", "amazon2023:P1:A:U:101"]
    assert {d["source_review_key"] for _, d in plan} == {"P1:A:U:100", "P1:A:U:101"}
    assert plan[0][1]["source_record_sha256"] == plan[1][1]["source_record_sha256"]


def test_legacy_record_roundtrips_the_source_fields():
    r = legacy_record(legacy("P1:A:U:100"))
    assert (r["parent_asin"], r["asin"], r["user_id"], r["timestamp"]) == ("P1", "A", "U", 100)
