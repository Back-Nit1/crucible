"""Day-1 check 4b/8: bounded per-category review coverage + running-shoe attribute probe.
Run: uv run python -m scripts.day1_coverage [--meta-mb 25 --review-mb 50 --windows 4] > docs/spikes/coverage.json
Windows are evenly spaced byte offsets across each remote file (deterministic, no RNG)."""
import argparse
import json
import re
import sys
import urllib.request
from collections import Counter

from catalog.indexing import sample_stats
from catalog.sources.amazon2023 import iter_jsonl, meta_url, review_url

# dataset category -> spec use-case segments (keyword matched against categories path + title)
SEGMENTS = {
    "Clothing_Shoes_and_Jewelry": {"running shoes": r"running", "clothing": r"\b(shirt|jacket|pants|dress|hoodie|jeans|sweater)\b"},
    "Sports_and_Outdoors": {"hiking/outdoor": r"hiking|camping", "water bottles": r"water bottle"},
    "Electronics": {"headphones": r"headphone|earbud", "PC components": r"computer components|graphics card|motherboard|\bssd\b"},
    "Video_Games": {"video games": r"."},
    "Office_Products": {"desks/office": r"\bdesk"},
    "Books": {"textbooks/study": r"textbook|study"},
    "Home_and_Kitchen": {"furniture": r"furniture"},
}
PROBE = {  # exact-ish key buckets; "Date First Available" and "Is Discontinued..." are NOT stock
    "size": re.compile(r"^(shoe |item )?size$|^size ", re.I), "width": re.compile(r"width", re.I),
    "weight": re.compile(r"weight", re.I), "stock/inventory": re.compile(r"stock|inventor|quantity", re.I)}


def size_of(url: str) -> int:
    req = urllib.request.Request(url, method="HEAD")
    return int(urllib.request.urlopen(req, timeout=60).headers["Content-Length"])


def windows(url: str, mb: int, n: int, cache: str):
    step = size_of(url) // n
    for i in range(n):
        yield from iter_jsonl(url, mb << 20, offset=i * step, cache_dir=cache)


def seg_text(m: dict) -> str:
    return (" ".join(map(str, m.get("categories") or [])) + " " + (m.get("title") or "")).lower()


def attr_probe(metas) -> dict:
    keys, hit = Counter(), Counter()
    for m in metas:
        d = m.get("details")
        d = d if isinstance(d, dict) else {}
        keys.update(d.keys())
        for name, rx in PROBE.items():
            hit[name] += any(rx.search(k) for k in d)
    return {"products": len(metas), "top_detail_keys": keys.most_common(12),
            "products_with_detail_key": {n: hit[n] for n in PROBE},
            "products_with_features": sum(bool(m.get("features")) for m in metas)}


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--meta-mb", type=int, default=25)
    a.add_argument("--review-mb", type=int, default=50)
    a.add_argument("--windows", type=int, default=4)
    a.add_argument("--cache", default="data/raw")
    a.add_argument("--only", nargs="*")
    args = a.parse_args()
    out = {"params": vars(args), "categories": {}}
    for cat, segs in SEGMENTS.items():
        if args.only and cat not in args.only:
            continue
        print(f"[{cat}]", file=sys.stderr)
        metas = list(windows(meta_url(cat), args.meta_mb, args.windows, args.cache))
        reviews = list(windows(review_url(cat), args.review_mb, args.windows, args.cache))
        r = {"meta_records": len(metas), "review_records": len(reviews), "all": sample_stats(metas, reviews)}
        r["segments"] = {s: sample_stats(sub, reviews) for s, rx in segs.items()
                         for sub in [[m for m in metas if re.search(rx, seg_text(m))]]}
        if cat == "Clothing_Shoes_and_Jewelry":  # the shoe probe, scoped to running-shoe products only
            shoes = [m for m in metas if re.search(r"running", seg_text(m)) and re.search(r"shoe|sneaker", seg_text(m))]
            r["running_shoe_attribute_probe"] = attr_probe(shoes)
        out["categories"][cat] = r
    json.dump(out, sys.stdout, indent=1, default=str)


if __name__ == "__main__":
    main()
