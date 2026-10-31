"""Build + (optionally) index the Amazon Reviews 2023 snapshot for one category.
  uv run python -m scripts.build_snapshot --category Sports_and_Outdoors --meta-mb 150 --review-mb 1500 --top-n 300
  ... --index --env-file .env      # embeds reviews/products and bulk-indexes into Elastic (idempotent by id)
Docs go to data/raw/ (gitignored); the manifest goes to data/manifests/<category>.json (committed)."""
import argparse
import json
import os
from pathlib import Path

from catalog.sources.amazon2023 import meta_url, review_url
from catalog.sources.snapshot import build, source_revision, stream_jsonl
from scripts._env import load


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--category", required=True)
    ap.add_argument("--meta-mb", type=int, default=150)
    ap.add_argument("--review-mb", type=int, default=1500)
    ap.add_argument("--top-n", type=int, default=300)
    ap.add_argument("--per-product", type=int, default=30)
    ap.add_argument("--index", action="store_true")
    ap.add_argument("--env-file")
    a = ap.parse_args()
    products, reviews, man = build(
        a.category, stream_jsonl(meta_url(a.category), a.meta_mb << 20), stream_jsonl(review_url(a.category), a.review_mb << 20),
        top_n=a.top_n, per_product=a.per_product, params={"meta_bytes": a.meta_mb << 20, "review_bytes": a.review_mb << 20},
        revision=source_revision())
    raw = Path("data/raw"); raw.mkdir(parents=True, exist_ok=True)
    (raw / f"snapshot_{a.category}.json").write_text(json.dumps({"products": products, "reviews": reviews}))
    Path("data/manifests").mkdir(parents=True, exist_ok=True)
    Path(f"data/manifests/{a.category}.json").write_text(json.dumps(man, indent=2) + "\n")
    print(json.dumps(man, indent=2))
    if a.index:
        if a.env_file:
            load(a.env_file, {"ELASTIC_API_KEY", "ELASTIC_ENDPOINT", "ELASTIC_CLOUD_ID"})
        from catalog.providers.elastic import Elastic, endpoint_from_cloud_id
        es = Elastic(os.environ.get("ELASTIC_ENDPOINT") or endpoint_from_cloud_id(os.environ["ELASTIC_CLOUD_ID"]))
        es.ensure_indices()
        for i in range(0, len(reviews), 16):
            vs = es.embed([f"{d['title']}. {d['text']}"[:1500] for d in reviews[i:i + 16]])
            for d, v in zip(reviews[i:i + 16], vs):
                d["embedding"] = v
        for i in range(0, len(products), 16):
            vs = es.embed([d["title"] for d in products[i:i + 16]])
            for d, v in zip(products[i:i + 16], vs):
                d["embedding"] = v
        es.bulk("reviews", [(d["review_id"], d) for d in reviews])
        es.bulk("products", [(d["product_id"], d) for d in products])
        print(f"indexed products={len(products)} reviews={len(reviews)}")


if __name__ == "__main__":
    main()
