import datetime as dt
from decimal import Decimal

import pytest

from catalog.providers.base import Product, Review
from catalog.router import ProviderRouter, ProviderUnavailable

T0 = dt.datetime(2023, 9, 1, tzinfo=dt.UTC)
CFG = {"live_chat": "channel3", "providers": {
    "elastic_snapshot": {"enabled": True, "reviews_source": "amazon2023"},
    "channel3": {"enabled": True}, "bestbuy": {"enabled": False}}}


class Fake:
    def __init__(self, source, prices, reviews=(), boom=False):
        self.source, self.reviews, self.boom = source, list(reviews), boom
        self.items = [Product(id=f"{source}-{i}", title="shoe", category="shoes", price=Decimal(p), source=source, as_of=T0)
                      for i, p in enumerate(prices)]

    def search(self, query, filters=None):
        if self.boom:
            raise RuntimeError("down")
        return self.items

    def get_product(self, pid):
        return next((p for p in self.items if p.id == pid), None)

    def get_reviews(self, pid, focus=None, limit=10):
        return [r for r in self.reviews if r.product_id == pid][:limit]


REV = Review(id="r1", product_id="amazon2023-0", rating=4, text="ok")


def router(**kw):
    return ProviderRouter({"elastic_snapshot": Fake("amazon2023", ["50", "90"], [REV]),
                           "channel3": Fake("channel3", ["40", "130"], boom=kw.get("boom", False)),
                           "bestbuy": Fake("bestbuy", ["1"])}, dict(CFG, live_chat=kw.get("live", "channel3")))


@pytest.mark.parametrize("mode", ["training", "eval"])
def test_training_and_eval_always_snapshot(mode):
    r = router().search("shoe", mode=mode)
    assert r.provider == "elastic_snapshot" and r.snapshot and r.source == "amazon2023" and r.as_of == T0


def test_live_uses_channel3_not_labelled_snapshot():
    r = router().search("shoe")
    assert (r.provider, r.snapshot, r.source) == ("channel3", False, "channel3")


def test_router_refilters_price_cap():
    assert [p.price for p in router().search("shoe", {"max_price": Decimal("100")}).products] == [Decimal("40")]


def test_live_falls_back_to_snapshot_and_says_so():
    r = router(boom=True).search("shoe")
    assert (r.provider, r.fallback_from, r.snapshot) == ("elastic_snapshot", "channel3", True)


def test_bestbuy_disabled_cannot_be_routed():
    with pytest.raises(ProviderUnavailable):
        router(live="bestbuy").search("shoe")


def test_missing_reviews_are_none_not_invented():
    r = router().get_reviews("channel3-0")
    assert r.reviews == [] and r.reviews_available is False


def test_snapshot_reviews_carry_source():
    r = router().get_reviews("amazon2023-0", mode="eval")
    assert r.reviews_available and r.source == "amazon2023" and r.snapshot


def test_unknown_variant_product_is_none():
    assert router().get_product("nope", mode="eval").product is None
