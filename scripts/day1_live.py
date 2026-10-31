"""Day-1 live probes (checks 4a and 7). Needs CHANNEL3_API_KEY / ELASTIC_API_KEY (+ ELASTIC_ENDPOINT or
ELASTIC_CLOUD_ID) in the environment, or `--env-file` (only those names are read; nothing is printed).
  uv run python -m scripts.day1_live channel3 --max-credits 20
  uv run python -m scripts.day1_live elastic --category Video_Games [--drop]"""
import argparse
import json
import os
import statistics
import sys
from pathlib import Path

from catalog.providers.channel3 import Channel3Provider
from catalog.providers.elastic import Elastic, endpoint_from_cloud_id, hybrid_review_query

NAMES = ("CHANNEL3_API_KEY", "ELASTIC_API_KEY", "ELASTIC_ENDPOINT", "ELASTIC_CLOUD_ID")
PROBES = [  # (spec category, query, filters)
    ("running shoes", "men's running shoes size 12", {"max_price": 100}),
    ("hiking/outdoor", "waterproof hiking boots", {"max_price": 150}),
    ("headphones", "wireless over-ear headphones", {"max_price": 100}),
    ("water bottles", "insulated stainless steel water bottle 32 oz", {}),
    ("desks/office", "standing desk", {"max_price": 400}),
    ("video games", "nintendo switch game", {"max_price": 60}),
    ("PC components", "nvidia graphics card", {}),
    ("textbooks", "calculus textbook", {}),
    ("clothing", "men's waterproof rain jacket", {"max_price": 120}),
    ("furniture", "ergonomic office chair", {"max_price": 300}),
    ("dev tools", "mechanical keyboard", {"max_price": 150}),
]


def load_env(path: str):
    for line in Path(path).read_text().splitlines():
        k, _, v = line.partition("=")
        if k.strip() in NAMES and v.strip():
            os.environ.setdefault(k.strip(), v.strip())


def has_key(o, needle="review") -> bool:
    if isinstance(o, dict):
        return any(needle in k.lower() or has_key(v, needle) for k, v in o.items())
    return isinstance(o, list) and any(has_key(v, needle) for v in o)


def stats(products: list[dict], max_price=None) -> dict:
    pct = lambda n: round(100 * n / len(products)) if products else None
    offers = [o for p in products for o in p.get("offers", [])]
    size_opts = [o for p in products for o in ((p.get("variants") or {}).get("options") or []) if o["name"].lower() == "size"]
    return {
        "n": len(products), "pct_with_offer": pct(sum(bool(p.get("offers")) for p in products)),
        "pct_instock_offer": pct(sum(any(o["availability"] == "InStock" for o in p.get("offers", [])) for p in products)),
        "pct_variants": pct(sum(bool(p.get("variants")) for p in products)),
        "pct_size_option": pct(sum(any(o["name"].lower() == "size" for o in ((p.get("variants") or {}).get("options") or [])) for p in products)),
        "size_available_populated_in_search": sum(v.get("available") is not None for o in size_opts for v in o["values"]),
        "pct_ratings": pct(sum(bool(p.get("ratings")) for p in products)),
        "median_rating_count": statistics.median([p["ratings"]["count"] for p in products if p.get("ratings")] or [0]),
        "pct_structured_attrs": pct(sum(bool(p.get("structured_attributes")) for p in products)),
        "attr_keys": sorted({k for p in products for k in (p.get("structured_attributes") or {})})[:12],
        "pct_key_features": pct(sum(bool(p.get("key_features")) for p in products)),
        "price_filter_violations": sum(o["price"]["price"] > max_price for o in offers) if max_price else None,
        "has_review_key": has_key(products),
        "category_slugs": sorted({(p.get("category") or {}).get("slug") or "?" for p in products})[:5],
    }


def channel3(a):
    c = Channel3Provider()
    out, raw = {"probes": {}}, {}
    for cat, q, f in PROBES:
        if c.credits_used >= a.max_credits:
            out["stopped_at_cap"] = cat
            break
        r = c.search_raw(q, f, limit=a.limit)
        raw[cat] = r
        out["probes"][cat] = stats(r["products"], f.get("max_price"))
    # attribute filter on the first probe, using a key the results actually exposed (1 credit)
    first = raw.get("running shoes", {}).get("products", [])
    sa = next(((k, v[0]) for p in first for k, v in (p.get("structured_attributes") or {}).items() if v), None)
    slug = next((p["category"]["slug"] for p in first if p.get("category")), None)
    if sa and slug and c.credits_used < a.max_credits:
        r = c.search_raw("running shoes", {"category_ids": [slug], "attributes": {sa[0]: [sa[1]]}}, limit=a.limit)
        out["attribute_filter_test"] = {"filter": {sa[0]: sa[1], "category": slug}, **stats(r["products"])}
    # product detail is free: does `available` get populated per variant value?
    det = []
    for p in [p for r in raw.values() for p in r["products"] if p.get("variants")][:4]:
        d = c._call("GET", f"/v1/products/{p['id']}")
        det.append([(o["name"], sum(v.get("available") is not None for v in o["values"]), len(o["values"]))
                    for o in (d.get("variants") or {}).get("options", [])])
    out["detail_variant_availability(name, populated, total)"] = det
    out.update(credits_used=c.credits_used, calls=len(c.calls))
    Path("data/raw").mkdir(parents=True, exist_ok=True)
    Path("data/raw/channel3_probe.json").write_text(json.dumps(raw))  # gitignored; Channel3 ToS: not for redistribution
    print(json.dumps(out, indent=1))


def elastic(a):
    from catalog.indexing import join, product_doc, review_doc
    from catalog.sources.amazon2023 import meta_url, review_url
    from scripts.day1_coverage import windows

    url = os.environ.get("ELASTIC_ENDPOINT") or endpoint_from_cloud_id(os.environ["ELASTIC_CLOUD_ID"])
    es = Elastic(url, prefix="spike_")
    info = es.call("GET", "/")
    print("connected:", {"build_flavor": info.get("version", {}).get("build_flavor"), "tagline": info.get("tagline")})
    eps = es.call("GET", "/_inference").get("endpoints", [])
    print("inference endpoints:", [(e["inference_id"], e["task_type"]) for e in eps])
    dims = len(es.embed(["probe"])[0])
    print("embedding dims:", dims)
    es.ensure_indices(dims)
    metas = list(windows(meta_url(a.category), 25, 4, "data/raw"))
    by = join(metas, windows(review_url(a.category), 50, 4, "data/raw"))
    mm = {m["parent_asin"]: m for m in metas}
    pick = sorted((p for p in by if len(by[p]) >= 5 and product_doc(mm[p], a.category, 0)), key=lambda p: -len(by[p]))[: a.products]
    revs = [r for p in pick for r in by[p]]
    rdocs = [review_doc(r) for r in revs]
    vecs = []
    for i in range(0, len(rdocs), 32):
        vecs += es.embed([f"{d['title']}. {d['text']}"[:1500] for d in rdocs[i:i + 32]])
    for d, v in zip(rdocs, vecs):
        d["embedding"] = v
    es.bulk("reviews", [(d["review_id"], d) for d in rdocs])
    pdocs = []
    for p in pick:
        d = product_doc(mm[p], a.category, len(by[p]))
        d["embedding"] = es.embed([d["title"]])[0]
        pdocs.append((p, d))
    es.bulk("products", pdocs)
    es.bulk("traces", [("t1", {"episode_id": "t1", "killed": True, "kill_reason": "wrong_refusal", "split": "train", "episode": {"x": 1}})])
    es.bulk("kill_rules", [("r1:1", {"rule_id": "r1", "version": 1, "description": "spike", "kills": 0})])
    es.bulk("generations", [("g0", {"gen_id": "g0", "generation": 0, "status": "done", "config": {"k": 1}})])
    print(f"indexed products={len(pdocs)} reviews={len(rdocs)}")
    pid = pick[0]
    for focus in a.focus:
        qv = es.embed([focus], input_type="search")[0]
        res = {}
        for name, body in (("hybrid", hybrid_review_query(pid, focus, qv, size=5)),
                           ("keyword", {"size": 5, "_source": ["review_id", "product_id", "text"], "query": {"bool": {"must": {"multi_match": {"query": focus, "fields": ["title^2", "text"]}}, "filter": {"term": {"product_id": pid}}}}}),
                           ("vector", {"size": 5, "_source": ["review_id", "product_id", "text"], "knn": {"field": "embedding", "query_vector": qv, "k": 5, "num_candidates": 50, "filter": {"term": {"product_id": pid}}}})):
            hits = es.call("POST", f"/{es.ix('reviews')}/_search", body)["hits"]["hits"]
            res[name] = [(h["_source"]["review_id"][-18:], h["_source"]["product_id"] == pid, h["_source"]["text"][:70]) for h in hits]
        print(json.dumps({"product": pid, "focus": focus, **res}, indent=1))
    print("traces back:", es.call("GET", f"/{es.ix('traces')}/_doc/t1")["_source"]["kill_reason"])
    if a.drop:
        for n in ("products", "reviews", "traces", "kill_rules", "generations"):
            es.call("DELETE", f"/{es.ix(n)}")
        print("dropped spike_ indices")


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--env-file")
    sub = a.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("channel3")
    c.add_argument("--max-credits", type=int, default=20)
    c.add_argument("--limit", type=int, default=20)
    e = sub.add_parser("elastic")
    e.add_argument("--category", default="Video_Games")
    e.add_argument("--products", type=int, default=25)
    e.add_argument("--focus", nargs="+", default=["stopped working after a few weeks", "battery life"])
    e.add_argument("--drop", action="store_true")
    args = a.parse_args()
    if args.env_file:
        load_env(args.env_file)
    {"channel3": channel3, "elastic": elastic}[args.cmd](args)


if __name__ == "__main__":
    main()
