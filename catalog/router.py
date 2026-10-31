"""ProviderRouter (spec 7.1): picks a CatalogProvider per request from config/providers.yaml and stamps
every result with its `source`, `as_of` and `snapshot` flag so the API/UI can show where data came from.
Training/eval always use the frozen Elastic snapshot (spec 6.2); Best Buy stays disabled."""
import datetime as dt
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel

from catalog.providers.base import CatalogProvider, Product, Review

Mode = Literal["live", "training", "eval"]
CONFIG = Path(__file__).resolve().parents[1] / "config" / "providers.yaml"
SNAPSHOT = "elastic_snapshot"


class ProviderUnavailable(Exception):
    pass


class Routed(BaseModel):
    provider: str
    source: str  # data origin, e.g. "amazon2023" / "channel3"
    as_of: dt.datetime | None  # oldest item timestamp; None when empty
    snapshot: bool  # True = frozen snapshot data, must be labelled as such
    fallback_from: str | None = None  # set when the preferred provider failed
    reviews_available: bool | None = None  # reviews results only


class SearchResult(Routed):
    products: list[Product]


class ProductResult(Routed):
    product: Product | None


class ReviewsResult(Routed):
    reviews: list[Review]


def load_config(path: Path = CONFIG) -> dict:
    return yaml.safe_load(path.read_text())


class ProviderRouter:
    def __init__(self, providers: dict[str, CatalogProvider], config: dict | None = None):
        self.providers = providers
        self.cfg = config or load_config()
        for name, c in (self.cfg.get("providers") or {}).items():
            if not c.get("enabled", False):
                self.providers.pop(name, None)  # disabled providers can never be routed to (e.g. bestbuy)

    def provider_name(self, mode: Mode) -> str:
        name = self.cfg["live_chat"] if mode == "live" else SNAPSHOT  # training/eval pinned to snapshot
        if name not in self.providers:
            raise ProviderUnavailable(name)
        return name

    def _run(self, mode: Mode, op, product_hint: str | None = None):
        """Run op(provider) on the mode's provider; live mode falls back to the snapshot on failure."""
        name = self.provider_name(mode)
        try:
            return name, None, op(self.providers[name])
        except Exception:
            if mode != "live" or name == SNAPSHOT or SNAPSHOT not in self.providers:
                raise
            return SNAPSHOT, name, op(self.providers[SNAPSHOT])

    def _stamp(self, name: str, items: list[Product], fb: str | None) -> dict:
        snap = name == SNAPSHOT
        return dict(provider=name, source=items[0].source if items else name, snapshot=snap,
                    as_of=min((p.as_of for p in items), default=None), fallback_from=fb)

    def search(self, query: str, filters: dict | None = None, mode: Mode = "live") -> SearchResult:
        name, fb, prods = self._run(mode, lambda p: p.search(query, filters))
        mx = (filters or {}).get("max_price")
        if mx is not None:  # never trust a provider's price filter (live offers can exceed it)
            prods = [p for p in prods if p.price <= mx]
        return SearchResult(products=prods, **self._stamp(name, prods, fb))

    def get_product(self, product_id: str, mode: Mode = "live") -> ProductResult:
        name, fb, prod = self._run(mode, lambda p: p.get_product(product_id))
        return ProductResult(product=prod, **self._stamp(name, [prod] if prod else [], fb))

    def get_reviews(self, product_id: str, focus: str | None = None, limit: int = 10, mode: Mode = "live") -> ReviewsResult:
        """Reviews come only from the provider that owns the product id. Empty = `reviews: none`, never invented."""
        name, fb, revs = self._run(mode, lambda p: p.get_reviews(product_id, focus, limit))
        base = self._stamp(name, [], fb)
        base["source"] = self.cfg["providers"].get(name, {}).get("reviews_source") or name
        return ReviewsResult(reviews=revs, reviews_available=bool(revs), **base)

    def _snapshot(self, mode: Mode):
        """The provider for `mode` as a SnapshotCatalog; live providers (Channel3) cannot enumerate."""
        name = self.provider_name(mode)
        prov = self.providers[name]
        if not hasattr(prov, "iter_products"):
            raise ProviderUnavailable(f"{name} cannot enumerate a frozen catalog")
        return name, prov

    def enumerate_products(self, category: str, mode: Mode = "training") -> SearchResult:
        """Explicit, complete, id-ordered enumeration of one category (the only supported enumeration path)."""
        if mode == "live":
            raise ProviderUnavailable("enumeration is a frozen-snapshot operation (training/eval only)")
        name, prov = self._snapshot(mode)
        prods = list(prov.iter_products(category))
        return SearchResult(products=prods, **self._stamp(name, prods, None))

    def review_ids(self, product_id: str, mode: Mode = "training") -> frozenset[str]:
        """Complete product-scoped review-id set; never truncated."""
        if mode == "live":
            raise ProviderUnavailable("complete review-id lookup is a frozen-snapshot operation")
        return self._snapshot(mode)[1].review_ids(product_id)

    def status(self) -> dict:
        return {"live_chat": self.cfg["live_chat"], "training_eval": SNAPSHOT,
                "providers": {n: {"enabled": n in self.providers, **c} for n, c in (self.cfg.get("providers") or {}).items()}}
