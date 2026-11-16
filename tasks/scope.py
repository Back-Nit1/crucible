"""A task sees only its own split's products, because its ground truth was built from exactly that pool.

`tasks.batch.generate_batch` derives each task's feasible set (and its "impossible" budget) from the products of the task's
split, split by a hash of (seed, category, product id), so train/val/test/held-out tasks are product-disjoint. A search over
the whole catalog also shows other splits' products: buying one is within budget yet fails the gate (`NOT_IN_FEASIBLE_SET`),
and an impossible task looks possible. `SplitScopedCatalog.for_task` gives the episode tools the same pool the task was made
from; scoring, payments and the gate keep the full catalog."""
from __future__ import annotations

from tasks.batch import BatchConfig, _product_split
from tasks.engine import SplitConfig
from tasks.schemas import TaskSpec


class _TaskView:
    def __init__(self, inner, ok):
        self._inner, self._ok = inner, ok

    def search(self, query, filters=None):
        return [p for p in self._inner.search(query, filters, size=1000) if self._ok(p)][:10]

    def get_product(self, product_id):
        product = self._inner.get_product(product_id)
        return product if product is not None and self._ok(product) else None

    def get_reviews(self, product_id, focus=None, limit=10):
        return self._inner.get_reviews(product_id, focus, limit) if self.get_product(product_id) else []

    def __getattr__(self, name):  # get_review_ids, iter_products: not narrowed
        return getattr(self._inner, name)


class SplitScopedCatalog:
    def __init__(self, inner, *, seed: int, categories, held_out_categories=frozenset(), split: SplitConfig):
        self._inner, self._seed = inner, seed
        self._config = BatchConfig(size=10, categories=tuple(categories), held_out_categories=frozenset(held_out_categories),
                                   split=split)

    def for_task(self, task: TaskSpec) -> _TaskView:
        return _TaskView(self._inner, lambda p: _product_split(p, p.category, self._seed, self._config) is task.split)

    def __getattr__(self, name):  # the full catalog for scoring, payments and the gate
        return getattr(self._inner, name)

    @classmethod
    def from_taskset(cls, inner, meta: dict) -> SplitScopedCatalog:
        from eval.taskset import EVAL_SPLIT
        return cls(inner, seed=meta["seed"], categories=meta["category_manifest_hashes"],
                   held_out_categories=meta.get("held_out_categories", ()), split=EVAL_SPLIT)
