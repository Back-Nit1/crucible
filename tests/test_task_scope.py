"""A task's tools show only its split's product pool; scoring keeps the full catalog."""
import datetime as dt
from decimal import Decimal

from catalog.providers.base import Product
from tasks.batch import BatchConfig, _product_split
from tasks.engine import SplitConfig
from tasks.scope import SplitScopedCatalog

CFG = dict(seed=7, categories=("Office",), split=SplitConfig(50, 10, 40))


class Stub:
    def __init__(self, products):
        self.products = {p.id: p for p in products}

    def search(self, query, filters=None, size=10):
        return list(self.products.values())[:size]

    def get_product(self, product_id):
        return self.products.get(product_id)

    def get_reviews(self, product_id, focus=None, limit=10):
        return ["review"]


def product(i):
    return Product(id=f"P{i}", title="t", category="Office", price=Decimal("1.00"), source="s", as_of=dt.datetime(2026, 1, 1))


def test_tools_see_only_the_tasks_split_pool_and_the_full_catalog_stays_reachable():
    products = [product(i) for i in range(60)]
    scoped = SplitScopedCatalog(Stub(products), **CFG)
    config = BatchConfig(size=10, categories=("Office",), split=SplitConfig(50, 10, 40))
    split = {p.id: _product_split(p, "Office", 7, config) for p in products}
    task = type("T", (), {"split": next(iter(split.values()))})()
    view = scoped.for_task(task)
    pool = {i for i, s in split.items() if s is task.split}
    assert {p.id for p in view.search("")} <= pool and len(pool) < len(products)
    outside = next(i for i in split if i not in pool)
    assert view.get_product(outside) is None and view.get_reviews(outside) == []
    assert scoped.get_product(outside).id == outside  # gate, payments and scoring read the full catalog
