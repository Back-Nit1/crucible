"""Read-through memoisation for a FROZEN snapshot provider. Safe only because the snapshot never changes
(results are keyed by the call arguments); never wrap a live provider with this."""
from catalog.providers.base import FrozenCatalogProvider


class FrozenCache:
    def __init__(self, inner: FrozenCatalogProvider):
        self.inner, self._c = inner, {}
        self.hits = self.misses = 0

    def _memo(self, key, fn):
        if key in self._c:
            self.hits += 1
        else:
            self.misses += 1
            self._c[key] = fn()
        return self._c[key]

    def search(self, query, filters=None):
        return list(self._memo(("s", query, tuple(sorted((filters or {}).items()))), lambda: tuple(self.inner.search(query, filters))))

    def get_product(self, product_id):
        return self._memo(("p", product_id), lambda: self.inner.get_product(product_id))

    def get_reviews(self, product_id, focus=None, limit=10):
        return list(self._memo(("r", product_id, focus, limit), lambda: tuple(self.inner.get_reviews(product_id, focus, limit))))

    def get_review_ids(self, product_id):
        return self._memo(("i", product_id), lambda: self.inner.get_review_ids(product_id))

    def iter_products(self, category, manifest_hash):
        return iter(self._memo(("c", category, manifest_hash), lambda: tuple(self.inner.iter_products(category, manifest_hash))))
