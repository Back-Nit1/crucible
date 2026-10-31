from decimal import Decimal

from catalog.providers.channel3 import Channel3Provider, build_filters

RAW = {
    "id": "p1", "title": "Trail Shoe", "brands": [{"id": "b", "name": "Acme"}],
    "category": {"slug": "running-shoes", "title": "Running Shoes"},
    "offers": [
        {"url": "u1", "domain": "a.com", "price": {"price": 90.0, "currency": "USD"}, "availability": "OutOfStock"},
        {"url": "u2", "domain": "b.com", "price": {"price": 110.5, "currency": "USD"}, "availability": "InStock"},
        {"url": "u3", "domain": "c.com", "price": {"price": 120, "currency": "USD"}, "availability": "InStock"},
    ],
    "variants": {"options": [{"name": "Size", "values": [{"label": "12", "exists": True, "available": "InStock"}]}]},
    "ratings": {"value": 4.4, "count": 10, "source_count": 2},
}


def fake(calls):
    def t(method, url, headers, body=None):
        calls.append((method, url, headers, body))
        return {"products": [RAW, {"id": "p2", "title": "no offers"}]} if method == "POST" else RAW
    return t


def test_filters_map_price_and_passthrough():
    assert build_filters({"max_price": 100, "category_ids": ["x"], "junk": 1}) == {
        "price": {"max_price": 100}, "category_ids": ["x"]}
    assert build_filters(None) == {}


def test_search_costs_one_credit_maps_product_and_skips_priceless():
    calls = []
    c = Channel3Provider("k", transport=fake(calls))
    out = c.search("shoes", {"max_price": 150})
    assert c.credits_used == 1 and calls[0][2]["x-api-key"] == "k"
    assert calls[0][3]["filters"] == {"price": {"max_price": 150}}
    assert [p.id for p in out] == ["p1"]  # p2 has no offer -> dropped, not invented
    p = out[0]
    assert p.price == Decimal("110.5") and p.source == "channel3" and p.as_of.tzinfo  # in-stock offer wins
    assert p.variants == {}  # no unit counts exist -> none synthesised
    assert p.attributes["variant_availability"] == {"Size": {"12": "InStock"}}


def test_product_detail_free_and_reviews_none():
    c = Channel3Provider("k", transport=fake([]))
    assert c.get_product("p1").id == "p1" and c.credits_used == 0
    assert c.get_reviews("p1") == []
