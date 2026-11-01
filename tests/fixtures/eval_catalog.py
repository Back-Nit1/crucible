"""Larger test-only synthetic FrozenCatalogProvider (NOT Amazon data) so product-disjoint splits are non-empty."""
import datetime as dt
from decimal import Decimal

from catalog.providers.base import Product, Review, ReviewIds, SnapshotMismatch

CATEGORIES = ("widgets", "gadgets", "gizmos")
HASHES = {c: format(i + 1, "x") * 64 for i, c in enumerate(CATEGORIES)}


class BigSynthetic:
    def __init__(self, per_category: int = 60):
        as_of = dt.datetime(2023, 9, 30, tzinfo=dt.UTC)
        self.products, self.reviews = {}, {}
        for c, cat in enumerate(CATEGORIES):
            for i in range(per_category):
                pid = f"{cat[:2].upper()}{i:03d}"
                self.products[pid] = Product(id=pid, title=f"{cat} model {i}", category=cat, price=Decimal(10 + 3 * i + c),
                                             source="synthetic-test-fixture", as_of=as_of, snapshot=True,
                                             manifest_hash=HASHES[cat], source_product_id=pid)
                revs = [Review(id=f"synthetic:{pid}:{k}", product_id=pid, rating=5.0, text="works great", date=dt.date(2023, 1, 1 + k))
                        for k in range(6)]
                if i % 4 == 0:  # every 4th product has a failure report -> review-trap material
                    revs.append(Review(id=f"synthetic:{pid}:x", product_id=pid, rating=1.0, text="it broke after a week",
                                       date=dt.date(2023, 2, 1)))
                self.reviews[pid] = revs

    def search(self, query, filters=None):
        return sorted(self.products.values(), key=lambda p: p.id)[:10]

    def get_product(self, pid):
        return self.products.get(pid)

    def get_reviews(self, pid, focus=None, limit=10):
        return list(self.reviews.get(pid, ()))[:limit]

    def get_review_ids(self, pid):
        return ReviewIds(True, frozenset(r.id for r in self.reviews[pid])) if pid in self.products else ReviewIds(False)

    def iter_products(self, category, manifest_hash):
        if HASHES.get(category) != manifest_hash:
            raise SnapshotMismatch(category)
        yield from sorted((p for p in self.products.values() if p.category == category), key=lambda p: p.id)
