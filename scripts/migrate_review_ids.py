"""One-off migration: legacy review ids (`parent_asin:asin:user:ts`, which collided) -> stable composite ids.
  uv run python -m scripts.migrate_review_ids --raw-dir <dir with snapshot_*.json> --env-file .env [--apply]
Without --apply it only reports the plan. With --apply it (1) bulk-writes every review under its new id, reusing the
stored embedding of the legacy doc (identical text => identical vector, no embedding calls), (2) verifies the new count,
then (3) deletes only legacy-schema docs (those lacking `source_review_key`) from the `reviews` index."""
import argparse
import glob
import json
import os
from collections import Counter

from catalog.indexing import review_doc
from scripts._env import load


def legacy_record(d: dict) -> dict:
    """Rebuild the source-record fields from a legacy doc (id = parent_asin:asin:user_id:timestamp)."""
    parent, asin, user, ts = d["review_id"].split(":")
    return {"parent_asin": parent, "asin": asin, "user_id": user, "timestamp": int(ts), "rating": d["rating"],
            "title": d.get("title"), "text": d["text"], "helpful_vote": d.get("helpful_votes", 0),
            "verified_purchase": d.get("verified", False)}


def migrate_docs(legacy_docs: list[dict]) -> list[tuple[str, dict]]:
    """(legacy_id, new_doc) in stable order; repeats of one source key get ordinals 0,1,2... in file order."""
    seen: Counter = Counter()
    out = []
    for d in legacy_docs:
        r = legacy_record(d)
        key = d["review_id"]
        new = review_doc(r, seen[(d["product_id"], key)])
        seen[(d["product_id"], key)] += 1
        new.update({k: d[k] for k in ("reviewer_context", "source", "as_of", "date") if k in d})  # keep provenance verbatim
        out.append((key, new))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", required=True)
    ap.add_argument("--env-file")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    legacy = [r for f in sorted(glob.glob(f"{a.raw_dir}/snapshot_*.json")) for r in json.load(open(f))["reviews"]]
    plan = migrate_docs(legacy)
    ids = [d["review_id"] for _, d in plan]
    assert len(ids) == len(set(ids)), "new ids must be unique"
    print(f"legacy rows={len(legacy)} distinct legacy ids={len({k for k, _ in plan})} new ids={len(set(ids))}")
    if not a.apply:
        return
    load(a.env_file or ".env", {"ELASTIC_API_KEY", "ELASTIC_ENDPOINT", "ELASTIC_CLOUD_ID"})
    from catalog.providers.elastic import Elastic, endpoint_from_cloud_id
    es = Elastic(os.environ.get("ELASTIC_ENDPOINT") or endpoint_from_cloud_id(os.environ["ELASTIC_CLOUD_ID"]))
    es.ensure_indices()
    # new mapping fields are added dynamically-safe via explicit put-mapping (idempotent)
    es.call("PUT", f"/{es.ix('reviews')}/_mapping", {"properties": {
        "source_review_key": {"type": "keyword"}, "source_ordinal": {"type": "integer"}, "source_record_sha256": {"type": "keyword"}}})
    vec: dict[str, list[float]] = {}
    uniq = sorted({k for k, _ in plan})
    for i in range(0, len(uniq), 200):
        got = es.call("POST", f"/{es.ix('reviews')}/_mget?_source=embedding", {"ids": uniq[i:i + 200]})
        for d in got["docs"]:
            if d.get("found"):
                vec[d["_id"]] = d["_source"]["embedding"]
    missing = [k for k in uniq if k not in vec]
    assert not missing, f"{len(missing)} legacy docs have no stored embedding; refusing to migrate"
    docs = [(d["review_id"], {**d, "embedding": vec[k]}) for k, d in plan]
    es.bulk("reviews", docs, chunk=100)
    n = es.call("POST", f"/{es.ix('reviews')}/_count", {"query": {"exists": {"field": "source_review_key"}}})["count"]
    assert n == len(docs), f"expected {len(docs)} migrated docs, found {n}; legacy docs left in place"
    out = es.call("POST", f"/{es.ix('reviews')}/_delete_by_query?refresh=true",
                  {"query": {"bool": {"must_not": {"exists": {"field": "source_review_key"}}}}})
    total = es.call("POST", f"/{es.ix('reviews')}/_count", {"query": {"match_all": {}}})["count"]
    print(f"migrated={n} deleted_legacy={out.get('deleted')} total_now={total}")


if __name__ == "__main__":
    main()
