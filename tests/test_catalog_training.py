import datetime as dt
from decimal import Decimal

import pytest

from catalog.providers.base import Product, Review
from catalog.router import ProviderRouter, ProviderUnavailable
from catalog.training import TrainingCatalog

T0 = dt.datetime(2023, 9, 30, tzinfo=dt.UTC)
CFG = {"live_chat": "channel3", "providers": {"elastic_snapshot": {"enabled": True, "reviews_source": "amazon2023"},
                                                "channel3": {"enabled": True}}}


class Snap:
    def __init__(self):
        self.items = [Product(id=f"P{i}", title="t", category="shoes", price=Decimal(10 * i), source="amazon2023", as_of=T0) for i in range(1, 6)]
        self.calls = []

    def iter_products(self, category):
        yield from (p for p in self.items if p.category == category)

    def review_ids(self, pid): return frozenset({"r1"})
    def search(self, q, filters=None): self.calls.append(("search", q)); return self.items[:1]
    def get_product(self, pid): return next((p for p in self.items if p.id == pid), None)
    def get_reviews(self, pid, focus=None, limit=10): self.calls.append(("reviews", limit)); return [Review(id="r1", product_id=pid, rating=5, text="x")]


class Live:
    def search(self, q, filters=None): return []


def router():
    return ProviderRouter({"elastic_snapshot": Snap(), "channel3": Live()}, CFG)


def test_empty_query_with_category_enumerates_completely_in_id_order():
    prods = TrainingCatalog(router()).search("", {"category": "shoes"})
    assert [p.id for p in prods] == ["P1", "P2", "P3", "P4", "P5"]


def test_enumeration_applies_price_cap_and_requires_a_category():
    c = TrainingCatalog(router())
    assert [p.id for p in c.search("", {"category": "shoes", "max_price": Decimal("20")})] == ["P1", "P2"]
    with pytest.raises(ValueError):
        c.search("", {})


def test_nonempty_query_is_ranked_search_not_enumeration():
    r = router()
    TrainingCatalog(r).search("shoe", {"category": "shoes"})
    assert r.providers["elastic_snapshot"].calls == [("search", "shoe")]


def test_training_view_never_reaches_live_provider_and_rejects_live_mode():
    with pytest.raises(ValueError):
        TrainingCatalog(router(), mode="live")
    with pytest.raises(ProviderUnavailable):
        router().enumerate_products("shoes", mode="live")


def test_live_provider_cannot_enumerate():
    r = ProviderRouter({"channel3": Live(), "elastic_snapshot": Snap()}, dict(CFG))
    r.cfg["live_chat"] = "channel3"
    assert r.review_ids("P1") == frozenset({"r1"})  # default mode is training -> snapshot
