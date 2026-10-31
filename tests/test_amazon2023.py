from decimal import Decimal

from catalog.sources.amazon2023 import coverage, parse_price


def test_parse_price():
    assert parse_price(12.99) == Decimal("12.99")
    assert parse_price(None) is None and parse_price("from $5") is None and parse_price(0) is None


def test_coverage_counts_usable():
    metas = [{"price": 10, "rating_number": 9, "features": ["x"]},
             {"price": None, "rating_number": 50},
             {"price": 5, "rating_number": 2}]
    assert coverage(metas) == {"products": 3, "price": 2, "reviews>=min": 2, "usable": 1, "features": 1}
