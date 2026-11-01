"""Seeded task batches over the REAL frozen snapshot: feasible, impossible and review-sensitive tasks.

Facts (products, prices, reviews, review ids) are read from the snapshot; only the shopper's message is generated.
Feasibility is computed by filtering the snapshot (category + price: the only checkable facts - Amazon data has no
stock/size). A review-sensitive task needs a persona-relevant concern backed by real review ids: here, a deterministic
keyword match on low-rated reviews ("durability" concern), recorded as such in `extraction_provenance`."""
from __future__ import annotations

import random
import re
from decimal import ROUND_CEILING, Decimal

from catalog.providers.base import FrozenCatalogProvider, Product
from tasks.engine import SplitConfig, build_review_trap, build_task, compute_feasible_set, select_best_value
from tasks.schemas import (HardConstraints, ImpliedNeed, ReviewPolarity, ReviewSignal, TaskSpec)

TASK_VERSION = "taskgen-v1"
CONCERN = "durability"
_BREAKS = re.compile(r"\b(broke|broken|fell apart|stopped working|died|defective|cracked|peeled|ripped|tore|leak(?:s|ed)?)\b", re.I)
MIN_REVIEWS = 5  # a "clean" alternative must have at least this many held reviews


def _cents(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.01"), rounding=ROUND_CEILING)


def durability_reviews(catalog: FrozenCatalogProvider, product_id: str):
    """Real low-rated reviews of the product whose text reports a failure (deterministic keyword match)."""
    return sorted((r for r in catalog.get_reviews(product_id, None, 100) if r.rating <= 2 and _BREAKS.search(r.text)),
                  key=lambda r: r.id)


def _trap_candidate(catalog, products: list[Product], budget: Decimal, constraints: HardConstraints):
    feasible = compute_feasible_set(products, constraints).product_ids
    best = select_best_value(products, feasible, budget, ())
    bad = durability_reviews(catalog, best) if best else []
    if not bad:
        return None
    clean = [pid for pid in feasible if pid != best and len(catalog.get_reviews(pid, None, 100)) >= MIN_REVIEWS
             and not durability_reviews(catalog, pid)]
    return (best, bad, clean[0]) if clean else None


def generate_tasks(catalog: FrozenCatalogProvider, manifests: dict[str, str], *, seed: int, count: int,
                   impossible_percent: int = 25, review_traps: int = 2, snapshot_id: str = "amazon2023-frozen",
                   split_config: SplitConfig = SplitConfig()) -> tuple[TaskSpec, ...]:
    """`count` tasks, deterministic for (catalog, seed): ~impossible_percent impossible, `review_traps` review-sensitive."""
    if count < 4:
        raise ValueError("need at least 4 tasks to mix feasible, impossible and review-sensitive")
    rng = random.Random(seed)
    cats = sorted(manifests)
    products = {c: sorted(catalog.iter_products(c, manifests[c]), key=lambda p: p.id) for c in cats}
    products = {c: ps for c, ps in products.items() if len(ps) >= 2}
    cats = sorted(products)
    if not cats:
        raise ValueError("snapshot has no category with two products")
    n_imp = max(1, round(count * impossible_percent / 100))
    kinds = ["impossible"] * n_imp + ["trap"] * min(review_traps, count - n_imp - 1)
    kinds += ["feasible"] * (count - len(kinds))
    rng.shuffle(kinds)
    tasks: list[TaskSpec] = []
    for i, kind in enumerate(kinds):
        tid, tseed = f"gen{seed}-{i:03d}", seed + i
        for attempt in range(200):  # bounded deterministic search for a category/budget that fits the kind
            cat = cats[rng.randrange(len(cats))]
            ps = products[cat]
            if kind == "impossible":
                floor = min(p.price for p in ps)
                if floor <= Decimal("0.01"):
                    continue
                budget = floor - Decimal("0.01")
            else:
                budget = _cents(ps[rng.randrange(len(ps))].price)
            hard = HardConstraints(category=cat, max_total=budget)
            if kind == "trap":
                found = _trap_candidate(catalog, ps, budget, hard)
                if not found:
                    continue
                best, bad, alt = found
                signal = ReviewSignal(
                    concern=CONCERN, product_id=best, polarity=ReviewPolarity.NEGATIVE,
                    claim=f"{len(bad)} low-rated review(s) report the product failing or breaking",
                    supporting_review_ids=tuple(r.id for r in bad[:3]), persona_relevance="shopper who needs it to last",
                    extraction_provenance="deterministic keyword match on <=2-star reviews (taskgen-v1)")
                task = build_task(task_id=tid, catalog_snapshot_id=snapshot_id, catalog=catalog,
                                  manifest_hash=manifests[cat], constraints=hard, seed=tseed, split_config=split_config,
                                  implied_needs=(ImpliedNeed(concern=CONCERN),), review_signals=(signal,))
                tasks.append(build_review_trap(task, alt, catalog))
                break
            task = build_task(task_id=tid, catalog_snapshot_id=snapshot_id, catalog=catalog, manifest_hash=manifests[cat],
                              constraints=hard, seed=tseed, split_config=split_config)
            if (kind == "impossible") == task.is_impossible and task.suitable_for_deterministic_training:
                tasks.append(task)
                break
        else:
            raise RuntimeError(f"could not construct a {kind} task for slot {i}")
    return tuple(tasks)
