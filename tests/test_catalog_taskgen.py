import datetime as dt
from decimal import Decimal

from catalog.providers.base import Product
from catalog.router import ProviderRouter
from catalog.taskgen import generate_tasks
from catalog.training import TrainingCatalog

T0 = dt.datetime(2023, 9, 30, tzinfo=dt.UTC)


class Snap:
    def __init__(self):
        self.items = [Product(id=f"P{i:03d}", title="t", category="Cat", price=Decimal(f"{5 + i}.99"), source="amazon2023", as_of=T0,
                              attributes={"main_category": "A" if i % 2 else "B"}) for i in range(40)]
        self.enumerated = 0

    def iter_products(self, category):
        self.enumerated += 1
        yield from sorted((p for p in self.items if p.category == category), key=lambda p: p.id)

    def review_ids(self, pid): return frozenset()
    def search(self, q, f=None): raise AssertionError("tasks must be built from enumeration, not ranked search")
    def get_product(self, pid): return None
    def get_reviews(self, pid, focus=None, limit=10): return []


def catalog():
    snap = Snap()
    cfg = {"live_chat": "elastic_snapshot", "providers": {"elastic_snapshot": {"enabled": True}}}
    return snap, TrainingCatalog(ProviderRouter({"elastic_snapshot": snap}, cfg))


def test_tasks_come_from_the_training_snapshot_enumeration_and_are_deterministic():
    snap, cat = catalog()
    a = generate_tasks(cat, ["Cat"], 12, seed=5, snapshot_id="s")
    b = generate_tasks(catalog()[1], ["Cat"], 12, seed=5, snapshot_id="s")
    assert [t.model_dump() for t in a] == [t.model_dump() for t in b] and snap.enumerated >= 12


def test_feasible_sets_are_real_and_impossible_tasks_have_a_real_closest_product():
    _, cat = catalog()
    tasks = generate_tasks(cat, ["Cat"], 40, seed=1, snapshot_id="s", impossible_fraction=0.3)
    real = {p.id: p for p in cat.enumerate("Cat")}
    assert any(t.is_impossible for t in tasks) and any(not t.is_impossible for t in tasks)
    for t in tasks:
        assert all(real[i].price <= t.hard_constraints.max_total for i in t.feasible_set)
        assert t.is_impossible == (not t.feasible_set)
        if t.is_impossible:
            assert t.closest_product_id in real
        assert t.hard_constraints.required_variant is None  # never generate unverifiable size/stock constraints
        assert not t.review_signals and not t.is_review_trap  # no unverified review claims


def test_unknown_or_empty_category_produces_no_tasks():
    _, cat = catalog()
    assert generate_tasks(cat, ["Nothing"], 3, seed=1, snapshot_id="s") == []


def test_intended_feasible_tasks_are_not_accidentally_impossible():
    _, cat = catalog()
    tasks = generate_tasks(cat, ["Cat"], 60, seed=9, snapshot_id="s", impossible_fraction=0.0)
    assert tasks and not any(t.is_impossible for t in tasks)


def test_impossible_mix_is_exact_not_sampled():
    _, cat = catalog()
    tasks = generate_tasks(cat, ["Cat"], 12, seed=3, snapshot_id="s", impossible_fraction=0.25)
    assert sum(t.is_impossible for t in tasks) == 3
