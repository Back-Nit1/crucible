"""Synthetic FrozenCatalogProvider for offline runtime tests. Marked test-only: NOT Amazon data, never presented as such."""
import datetime as dt
import re
from decimal import Decimal

from catalog.providers.base import Product, Review, ReviewIds, SnapshotMismatch

HASHES = {"widgets": "w" * 64, "gadgets": "g" * 64}
WORDS = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel"]


class SyntheticFrozen:
    def __init__(self):
        as_of = dt.datetime(2023, 9, 30, tzinfo=dt.UTC)
        self.products, self.reviews = {}, {}
        for c, cat in enumerate(HASHES):
            for i in range(8):
                pid = f"{cat[:1].upper()}{i:03d}"
                self.products[pid] = Product(id=pid, title=f"{WORDS[i]} {cat} pro {WORDS[(i + c) % 8]} model", category=cat,
                                             price=Decimal(10 + 7 * i + c), source="synthetic-test-fixture", as_of=as_of,
                                             snapshot=True, manifest_hash=HASHES[cat], source_product_id=pid)
                revs = [Review(id=f"synthetic:{pid}:{k}", product_id=pid, rating=float(5 - (k % 4)),
                               text="it works great" if k % 4 == 0 else "mixed feelings", date=dt.date(2023, 1, 1 + k))
                        for k in range(8)]
                if i in (0, 1):  # cheapest items: low-rated reviews report failure -> review-trap material
                    revs.append(Review(id=f"synthetic:{pid}:x", product_id=pid, rating=1.0,
                                       text="it broke after a week", date=dt.date(2023, 2, 1)))
                self.reviews[pid] = revs

    def search(self, query, filters=None):
        f, words = filters or {}, set(re.findall(r"[a-z]+", query.lower()))
        hits = [p for p in self.products.values() if words & set(p.title.lower().split())
                and (not f.get("category") or p.category == f["category"])
                and (f.get("max_price") is None or p.price <= Decimal(str(f["max_price"])))]
        return sorted(hits, key=lambda p: p.id)[:10]

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
