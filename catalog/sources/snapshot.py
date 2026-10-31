"""Deterministic, bounded Amazon Reviews 2023 snapshot builder (spec 8.1).
Rule (recorded in the manifest): candidates = the `top_n` priced products by declared rating_number found in the first
`meta_bytes` of meta_<cat>.jsonl; reviews = first `review_bytes` of <cat>.jsonl streamed in file order, keeping at most
`per_product` reviews per candidate; a candidate is kept only if it holds >= `min_reviews` real reviews.
Nothing is generated: every doc is a verbatim projection of a source record, joined on parent_asin."""
import datetime as dt
import hashlib
import json
import urllib.request

from catalog.indexing import product_doc, review_doc
from catalog.sources.amazon2023 import meta_url, parse_price, review_url

DATASET_API = "https://huggingface.co/api/datasets/McAuley-Lab/Amazon-Reviews-2023"


def stream_jsonl(url: str, max_bytes: int, opener=urllib.request.urlopen):
    """Yield records from the first `max_bytes` of a remote JSONL, streaming (no full-file read). Partial last line dropped."""
    req = urllib.request.Request(url, headers={"Range": f"bytes=0-{max_bytes - 1}"})
    with opener(req, timeout=300) as r:
        buf = b""
        while chunk := r.read(1 << 20):
            *lines, buf = (buf + chunk).split(b"\n")
            for line in lines:
                if line:
                    yield json.loads(line)


def source_revision(opener=urllib.request.urlopen) -> str | None:
    try:
        with opener(urllib.request.Request(DATASET_API), timeout=30) as r:
            return json.load(r).get("sha")
    except Exception:  # revision is provenance, not a hard dependency
        return None


def build(category: str, meta_stream, review_stream, top_n=300, per_product=30, min_reviews=5,
          params: dict | None = None, revision: str | None = None, now: dt.datetime | None = None):
    cands = {}
    for m in meta_stream:
        if parse_price(m.get("price")) is not None and m.get("title") and m.get("rating_number"):
            cands[m["parent_asin"]] = m
    cands = dict(sorted(cands.items(), key=lambda kv: (-kv[1]["rating_number"], kv[0]))[:top_n])
    held: dict[str, list[dict]] = {k: [] for k in cands}
    seen = 0
    for r in review_stream:
        seen += 1
        h = held.get(r.get("parent_asin"))
        if h is not None and len(h) < per_product and r.get("text"):
            h.append(r)
    keep = [p for p in cands if len(held[p]) >= min_reviews]
    products = [product_doc(cands[p], category, len(held[p])) for p in keep]
    reviews = [review_doc(r) for p in keep for r in held[p]]
    digest = hashlib.sha256("\n".join(sorted(d["product_id"] for d in products) + sorted(d["review_id"] for d in reviews)).encode()).hexdigest()
    manifest = {
        "source": "amazon2023", "citation": "Hou et al. 2024, arXiv:2403.03952", "category": category,
        "retrieved_at": (now or dt.datetime.now(dt.UTC)).isoformat(), "source_revision": revision,
        "meta_url": meta_url(category), "review_url": review_url(category),
        "sample_rule": {"top_n": top_n, "per_product": per_product, "min_reviews": min_reviews, **(params or {}),
                        "order": "candidates by -rating_number,parent_asin; reviews in file order"},
        "review_records_scanned": seen, "candidates": len(cands), "products": len(products), "reviews": len(reviews),
        "sha256": digest,
    }
    return products, reviews, manifest
