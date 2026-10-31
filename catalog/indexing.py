"""Bounded Amazon Reviews 2023 -> Elastic docs. Joins reviews to product metadata by parent_asin.
Provenance: every doc carries source + as_of. The dataset has NO review id field, so the review id
is composed only from original fields (parent_asin:asin:user_id:timestamp) - nothing is invented."""
import datetime as dt
import hashlib
from collections import Counter, defaultdict

from catalog.sources.amazon2023 import parse_price

SOURCE = "amazon2023"
AS_OF = dt.datetime(2023, 9, 30, tzinfo=dt.UTC)  # dataset runs to Sep 2023 (spec 7)


def review_id(r: dict) -> str:
    return f"{r['parent_asin']}:{r['asin']}:{r['user_id']}:{r['timestamp']}"


def canonical_review_id(source: str, product_id: str, source_review_id: str, occurrence: int = 0) -> str:
    """Stable, collision-free id from (source, product, original review id). `occurrence` > 0 only disambiguates
    byte-identical source duplicates (file order), so every stored review keeps a distinct id."""
    digest = hashlib.sha256(source_review_id.encode()).hexdigest()[:16]
    return f"{source}:{product_id}:{digest}" + (f"-{occurrence}" if occurrence else "")


def legacy_to_canonical(legacy_id: str, source: str = SOURCE) -> str:
    """Migrate a v1 citation (`parent_asin:asin:user:ts`, no source prefix) to its canonical id."""
    return canonical_review_id(source, legacy_id.split(":", 1)[0], legacy_id)


def product_doc(m: dict, category: str, n_reviews: int) -> dict | None:
    """None when there is no real price (unusable for budget tasks). Sizes/stock don't exist in this
    dataset, so `variants` is empty and nothing is synthesised."""
    price = parse_price(m.get("price"))
    if price is None:
        return None
    imgs = m.get("images") or []
    return {
        "product_id": m["parent_asin"], "title": m["title"], "brand": m.get("store"), "category": category,
        "price": float(price), "currency": "USD", "variants": {},
        "source_product_id": m["parent_asin"],
        "attributes": {"main_category": m.get("main_category"), "categories": m.get("categories"),
                       "features": m.get("features"), "details": m.get("details")},
        "image_url": (imgs[0].get("large") if imgs else None),
        "rating_average": m.get("average_rating"), "rating_count": m.get("rating_number"),
        "reviews_indexed": n_reviews, "source": SOURCE, "as_of": AS_OF.isoformat(),
    }


def review_doc(r: dict, occurrence: int = 0) -> dict:
    return {
        "review_id": canonical_review_id(SOURCE, r["parent_asin"], review_id(r), occurrence),
        "source_review_id": review_id(r), "product_id": r["parent_asin"], "rating": r["rating"],
        "title": r.get("title"), "text": r.get("text") or "",
        "date": dt.datetime.fromtimestamp(r["timestamp"] / 1000, dt.UTC).date().isoformat(),
        "helpful_votes": r.get("helpful_vote", 0), "verified": bool(r.get("verified_purchase")),
        "reviewer_context": {}, "source": SOURCE, "as_of": AS_OF.isoformat(),
    }


def join(metas, reviews) -> dict[str, list[dict]]:
    """parent_asin -> its reviews, for products present in `metas` (reviews without metadata are dropped)."""
    ids = {m["parent_asin"] for m in metas}
    out = defaultdict(list)
    for r in reviews:
        if r["parent_asin"] in ids:
            out[r["parent_asin"]].append(r)
    return out


def sample_stats(metas, reviews, min_reviews: int = 5) -> dict:
    """Per-category coverage over a bounded sample. `usable` = real price + >= min_reviews real reviews held."""
    by = join(metas, reviews)
    c = Counter(products=len(metas), reviews_joined=sum(map(len, by.values())))
    for m in metas:
        priced = parse_price(m.get("price")) is not None
        n = len(by.get(m["parent_asin"], []))
        c["price"] += priced
        c["declared>=min"] += (m.get("rating_number") or 0) >= min_reviews
        c["sample>=min"] += n >= min_reviews
        c["usable"] += priced and n >= min_reviews
        c["features"] += bool(m.get("features"))
    return dict(c)
