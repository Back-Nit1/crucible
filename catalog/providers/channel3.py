"""Channel3 provider (spec 7.1). Endpoints/fields verified against channel3.ai/docs on 2026-10-31:
POST /v1/search (1 credit), GET /v1/products/{id} (free), auth header `x-api-key`.
Channel3 exposes only a ratings rollup, no review text, so get_reviews() is always empty
(spec 8.1: no reviews -> `reviews: none`, never generated). Live chat only: its ToS bars
training on, and bulk-storing, Customer Output (see docs/spikes/catalog-elastic.md)."""
import datetime as dt
import os
from decimal import Decimal

from catalog.providers._http import request_json
from catalog.providers.base import Product, Review

BASE = "https://api.trychannel3.com"
# our filter key -> Channel3 SearchFilters key (docs: api-reference/v1/search)
_PASS = ("brand_ids", "category_ids", "website_ids", "attributes", "gender", "age", "colors", "dimensions")


def build_filters(filters: dict | None) -> dict:
    f = filters or {}
    out = {k: f[k] for k in _PASS if f.get(k) is not None}
    if f.get("min_price") is not None or f.get("max_price") is not None:
        out["price"] = {k: f[k] for k in ("min_price", "max_price") if f.get(k) is not None}
    return out


def to_product(raw: dict, as_of: dt.datetime) -> Product | None:
    """Map a Channel3 product. None when it has no offer (no real price -> unusable).
    Channel3 reports InStock/OutOfStock per variant value, never unit counts, so `variants`
    stays empty and availability lives in attributes (no stock is synthesised)."""
    offers = raw.get("offers") or []
    if not offers:
        return None
    best = min((o for o in offers if o["availability"] == "InStock") or offers,
               key=lambda o: Decimal(str(o["price"]["price"])))
    options = (raw.get("variants") or {}).get("options") or []
    attrs = {
        "structured_attributes": raw.get("structured_attributes") or {},
        "key_features": raw.get("key_features"),
        "materials": raw.get("materials"),
        "ratings": raw.get("ratings"),  # rollup only: {value, count, source_count}
        "offer_availability": best["availability"],
        "merchant_domain": best["domain"],
        "variant_availability": {o["name"]: {v["label"]: v.get("available") for v in o["values"]} for o in options},
    }
    return Product(
        id=raw["id"], title=raw["title"],
        brand=(raw.get("brands") or [{}])[0].get("name"),
        category=((raw.get("category") or {}).get("slug")) or "unknown",
        price=Decimal(str(best["price"]["price"])), currency=best["price"]["currency"],
        attributes=attrs, source="channel3", as_of=as_of,
    )


class Channel3Provider:
    def __init__(self, api_key: str | None = None, transport=request_json):
        self.key = api_key or os.environ["CHANNEL3_API_KEY"]
        self.transport = transport
        self.credits_used = 0  # per pricing doc: search=1, product detail=free
        self.calls: list[str] = []

    def _call(self, method, path, body=None, credits=0):
        self.calls.append(f"{method} {path}")
        out = self.transport(method, BASE + path, {"x-api-key": self.key, "Content-Type": "application/json"}, body)
        self.credits_used += credits
        return out

    def search_raw(self, query: str, filters: dict | None = None, limit: int = 20, mode: str = "default") -> dict:
        body = {"query": query, "limit": limit, "config": {"mode": mode}}
        f = build_filters(filters)
        if f:
            body["filters"] = f
        return self._call("POST", "/v1/search", body, credits=1)

    def search(self, query: str, filters: dict | None = None, limit: int = 20) -> list[Product]:
        now = dt.datetime.now(dt.UTC)
        raw = self.search_raw(query, filters, limit)
        return [p for p in (to_product(r, now) for r in raw.get("products", [])) if p]

    def get_product(self, product_id: str) -> Product | None:
        raw = self._call("GET", f"/v1/products/{product_id}")
        return to_product(raw, dt.datetime.now(dt.UTC))

    def get_reviews(self, product_id: str, focus: str | None = None, limit: int = 10) -> list[Review]:
        return []  # ponytail: Channel3 has no review-text endpoint; ratings rollup is in attributes["ratings"]
