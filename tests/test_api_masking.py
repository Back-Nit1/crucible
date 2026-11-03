"""DEMO_MODE=1 hides third-party brand names in every product-bearing API response."""
import json

import pytest
from fastapi.testclient import TestClient

from api.buyer import BuyerService
from api.main import create_app
from api.masking import HIDDEN, hide, mask_product
from catalog.router import ProviderRouter
from tests.fixtures.frozen import SyntheticFrozen
from tests.test_api_buyer import MSG, build, start
from tests.test_api_endpoints import CFG


class Branded(SyntheticFrozen):
    """Every product gets its title's first word as a brand, plus a brand-ish attribute."""

    def __init__(self):
        super().__init__()
        for pid, p in list(self.products.items()):
            self.products[pid] = p.model_copy(update={"brand": p.title.split()[0], "attributes": {"Brand": p.title.split()[0], "color": "red"}})


def brands(cat):
    return {p.brand for p in cat.products.values()}


def app_client(cat):
    return TestClient(create_app(ProviderRouter({"elastic_snapshot": cat}, CFG)), raise_server_exceptions=False)


def test_hide_is_case_insensitive_and_inert_outside_demo_mode(monkeypatch):
    monkeypatch.delenv("DEMO_MODE", raising=False)
    assert hide("Nike shoe", "nike") == "Nike shoe"
    monkeypatch.setenv("DEMO_MODE", "1")
    assert hide("Nike shoe, NIKE fit", "nike") == f"{HIDDEN} shoe, {HIDDEN} fit"
    assert hide("shoe", None) == "shoe" and hide(None, "nike") is None and hide("a.b", "a.b") == HIDDEN  # brand is not a regex


def test_catalog_routes_hide_brand_in_demo_mode_and_show_it_otherwise(monkeypatch):
    cat = Branded()
    pid = next(iter(cat.products))
    brand = cat.products[pid].brand
    monkeypatch.delenv("DEMO_MODE", raising=False)
    off = app_client(cat)
    assert off.get(f"/catalog/products/{pid}").json()["product"]["brand"] == brand
    monkeypatch.setenv("DEMO_MODE", "1")
    on = app_client(cat)
    for body in (on.get(f"/catalog/products/{pid}").text, on.get("/catalog/search", params={"q": "widgets"}).text):
        assert brand.lower() not in body.lower().replace("brand", "") and HIDDEN in body
    assert on.get(f"/catalog/products/{pid}").json()["product"]["brand"] is None
    assert "Brand" not in on.get(f"/catalog/products/{pid}").json()["product"]["attributes"]


def test_buyer_events_hide_brand_in_cards_comparison_and_confirmation(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "1")
    c, backend, service, *_ = build()
    cat = service.catalog
    for pid, p in list(cat.products.items()):
        cat.products[pid] = p.model_copy(update={"brand": p.title.split()[0]})
    text = json.dumps(start(c).json()).lower()
    assert HIDDEN in text
    for b in brands(cat):
        assert b.lower() not in text, b
    run = start(c).json()
    cards = [e for e in run["events"] if e["type"] == "product_card"]
    assert cards and all(e["brand"] is None for e in cards)
    assert all(v is None for e in run["events"] if e["type"] == "comparison" for v in e["rows"]["brand"].values())


def test_buyer_events_keep_brand_without_demo_mode(monkeypatch):
    monkeypatch.delenv("DEMO_MODE", raising=False)
    c, backend, service, *_ = build()
    cat = service.catalog
    for pid, p in list(cat.products.items()):
        cat.products[pid] = p.model_copy(update={"brand": p.title.split()[0]})
    cards = [e for e in start(c).json()["events"] if e["type"] == "product_card"]
    assert cards and all(e["brand"] for e in cards)


def test_mask_product_passes_none_through(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "1")
    assert mask_product(None) is None
