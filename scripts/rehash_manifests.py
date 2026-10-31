"""Recompute each category manifest's counts + sha256 from the LIVE Elastic snapshot (after a review-id migration).
  uv run python -m scripts.rehash_manifests --env-file "<path to .env>"           # dry run: prints old/new
  uv run python -m scripts.rehash_manifests --env-file ... --write                 # rewrites data/manifests/*.json"""
import argparse
import json
import os
from collections import defaultdict
from pathlib import Path

from catalog.providers.elastic import MANIFEST_DIR, Elastic, endpoint_from_cloud_id
from catalog.sources.snapshot import snapshot_digest
from scripts._env import load


def live_snapshots(es) -> dict[str, tuple[list[str], list[str]]]:
    cat_of, by_cat = {}, defaultdict(lambda: ([], []))
    for src, _ in es.scan("products", {"match_all": {}}, "product_id", ["product_id", "category"]):
        cat_of[src["product_id"]] = src["category"]
        by_cat[src["category"]][0].append(src["product_id"])
    for src, _ in es.scan("reviews", {"match_all": {}}, "review_id", ["review_id", "product_id"]):
        by_cat[cat_of[src["product_id"]]][1].append(src["review_id"])
    return by_cat


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file", required=True)
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    load(a.env_file, {"ELASTIC_API_KEY", "ELASTIC_ENDPOINT", "ELASTIC_CLOUD_ID"})
    es = Elastic(os.environ.get("ELASTIC_ENDPOINT") or endpoint_from_cloud_id(os.environ["ELASTIC_CLOUD_ID"]))
    for cat, (pids, rids) in sorted(live_snapshots(es).items()):
        path = Path(MANIFEST_DIR) / f"{cat}.json"
        old = json.loads(path.read_text())
        new = {**old, "products": len(pids), "reviews": len(rids), "sha256": snapshot_digest(pids, rids)}
        print(f"{cat}: products {old['products']}->{new['products']} reviews {old['reviews']}->{new['reviews']} "
              f"sha {old['sha256'][:12]}->{new['sha256'][:12]}")
        if a.write:
            path.write_text(json.dumps(new, indent=2) + "\n")


if __name__ == "__main__":
    main()
