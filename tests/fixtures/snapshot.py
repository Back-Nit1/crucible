"""Shared fake frozen snapshot (a TrainingCatalog backend) for integration tests."""
import datetime as dt
from decimal import Decimal

from catalog.providers.base import Product, Review
from catalog.router import ProviderRouter
from catalog.training import TrainingCatalog

T0 = dt.datetime(2023, 9, 30, tzinfo=dt.UTC)
TITLES = ["Insulated Steel Water Bottle", "Plastic Water Bottle Kids", "Hiking Water Bottle Large", "Cotton Running Shirt",
          "Trail Running Shoe", "Yoga Mat Thick", "Camping Water Bottle Clip"] * 4


class Snap:
    def __init__(self):
        self.items = [Product(id=f"P{i:03d}", title=f"{t} {i}", category="Cat", price=Decimal(f"{5 + 2 * i}.00"), source="amazon2023",
                              as_of=T0, attributes={"main_category": "A"}) for i, t in enumerate(TITLES)]

    def iter_products(self, c): yield from (p for p in self.items if p.category == c)
    def review_ids(self, pid): return frozenset(r.id for r in self.get_reviews(pid))
    def search(self, q, f=None):
        words = set(q.lower().split())
        out = [p for p in self.items if words & set(p.title.lower().split())
               and (not f or f.get("max_price") is None or p.price <= Decimal(str(f["max_price"])))]
        return out[:10]
    def get_product(self, pid): return next((p for p in self.items if p.id == pid), None)
    def get_reviews(self, pid, focus=None, limit=10):
        return [Review(id=f"amazon2023:{pid}:{k}", product_id=pid, rating=4.0, text=f"Held up well after {k} months <br /> of use") for k in range(3)][:limit]




def training_catalog():
    cfg = {"live_chat": "elastic_snapshot", "providers": {"elastic_snapshot": {"enabled": True}}}
    return TrainingCatalog(ProviderRouter({"elastic_snapshot": Snap()}, cfg))
