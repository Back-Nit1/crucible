"""Seeded generation of real tasks over the frozen snapshot, via `tasks.engine.build_task` (Agent 2's algorithms, unchanged).

Constraints are derived only from facts present in the snapshot: category, a price cap taken from the category's real
price quantiles (or just below its cheapest product for deliberately impossible tasks), and an optional equality on the
checkable `main_category` attribute. No size/stock/shipping constraint is ever generated (the data has none), and no
review signals or review traps are claimed (those need extracted, verified review evidence)."""
import random
from decimal import ROUND_HALF_UP, Decimal

from catalog.providers.base import CatalogProvider
from tasks.engine import SplitConfig, build_task
from tasks.schemas import AttributeConstraint, ConstraintOperator, Difficulty, HardConstraints, TaskSpec

_CENT = Decimal("0.01")


def _quantile(prices: list[Decimal], q: float) -> Decimal:
    return prices[min(len(prices) - 1, int(q * len(prices)))]


def generate_tasks(catalog: CatalogProvider, categories: list[str], per_category: int, seed: int, snapshot_id: str,
                   impossible_fraction: float = 0.25, split_config: SplitConfig = SplitConfig()) -> list[TaskSpec]:
    rng = random.Random(seed)
    tasks: list[TaskSpec] = []
    for category in categories:
        products = sorted(catalog.search("", {"category": category}), key=lambda p: (p.price, p.id))
        if not products:
            continue  # nothing real to build a task from
        prices = [p.price for p in products]
        mains = sorted({p.attributes.get("main_category") for p in products if p.attributes.get("main_category")})
        for i in range(per_category):
            impossible = rng.random() < impossible_fraction
            attrs: tuple[AttributeConstraint, ...] = ()
            if mains and rng.random() < 0.5:
                attrs = (AttributeConstraint(attribute="main_category", operator=ConstraintOperator.EQ,
                                             values=(rng.choice(mains),)),)
            if impossible:  # below the cheapest real product: provably no feasible item
                cap = max(_CENT, (prices[0] - _CENT))
            else:
                cap = _quantile(prices, rng.choice((0.25, 0.5, 0.75))).quantize(_CENT, ROUND_HALF_UP)
            task = build_task(
                task_id=f"{category.lower()}-s{seed}-{i:03d}", catalog_snapshot_id=snapshot_id, catalog=catalog,
                constraints=HardConstraints(category=category, max_total=cap, attributes=attrs),
                seed=rng.randrange(2**31), split_config=split_config, difficulty=Difficulty.MEDIUM)
            n = len(task.feasible_set)
            difficulty = Difficulty.HARD if task.is_impossible or n <= 3 else Difficulty.MEDIUM if n <= 15 else Difficulty.EASY
            tasks.append(task.model_copy(update={"difficulty": difficulty}))
    return tasks
