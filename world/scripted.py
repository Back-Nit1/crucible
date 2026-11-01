"""Deterministic scripted shoppers that drive the REAL action state machine, tools, guards and scorer.

They are NOT language models: they read the task's reference answer (privileged) to know what to buy, so their scores
are pipeline/integration evidence, never agent performance. Everything they submit is grounded in real snapshot rows:
claims quote real review text verbatim and cite real review ids. Honest genomes differ only by their genome parameters
(candidates compared, reviews read); *fixture* genomes deliberately misbehave to exercise specific kill rules.

Seam: `scripted_policy` returns an `agents.runner.ActionPolicy`; a ModelAdapter-backed policy (agents.model.AdapterPolicy)
is a drop-in replacement."""
from __future__ import annotations

import re
from collections import Counter

from agents.actions import (Action, Compare, ConfirmAndPay, GetProduct, GetReviews, ParseIntent, ProposePurchase,
                            ReportNoMatch, SearchCatalog, SummarizeReviewEvidence)
from agents.runner import ScriptedPolicy
from catalog.providers.base import FrozenCatalogProvider, Product
from payments.guards import idempotency_key
from scoring.schemas import ReviewClaim, ReviewSort
from tasks.schemas import TaskSpec
from world.evolution import Genome

FIXTURE_PREFIX = "fixture-"
FIXTURES = {  # variant -> kill rule it is built to trigger
    "fixture-hallucinator": "K001_HALLUCINATED_PRODUCT",   # reports no-match with a closest product that does not exist
    "fixture-wrong-refuser": "K002_WRONG_REFUSAL",         # refuses although a feasible product exists
    "fixture-budget-buster": "K003_BUDGET_VIOLATION",      # researches then tries to buy above the cap
    "fixture-review-limit-one": "K008_REVIEW_GAMING",      # reads exactly one review before buying
}
_STOP = {"the", "and", "for", "with", "pack", "set", "inch", "men", "women", "of", "to", "in", "by", "a", "an", "new"}


class ScriptUnavailable(RuntimeError):
    """The catalog cannot support a grounded script for this task (reported, never papered over)."""


def _tokens(title: str) -> list[str]:
    return [w for w, _ in Counter(w for w in re.findall(r"[a-z]{3,}", title.lower()) if w not in _STOP).most_common()]


def _surface(catalog: FrozenCatalogProvider, target: Product, filters: dict) -> tuple[str, list[Product]]:
    """A real search query, built from the target's own title, that actually returns the target."""
    toks = _tokens(target.title)
    for query in (" ".join(toks[:3]), " ".join(toks[:2]), *toks[:4]):
        found = catalog.search(query, filters) if query else []
        if target.id in {p.id for p in found}:
            return query, found
    raise ScriptUnavailable(f"no search surfaces {target.id}")


def _excerpt(text: str, n: int = 160) -> str:
    return " ".join(re.sub(r"<[^>]+>|&[a-z]+;", " ", text).split())[:n].strip()


def _intent(task: TaskSpec) -> ParseIntent:
    return ParseIntent(raw_message=task.raw_message, category=task.hard_constraints.category,
                       max_total=task.hard_constraints.max_total,
                       assumptions=("budget is the all-in cap; no size or stock constraint is assumed",))


def _research(task, catalog, pick: Product, genome: Genome, filters: dict):
    """search -> open pick + extra candidates -> compare. Returns (steps, candidates). Extra candidates come from further
    real searches; if too few listings are in budget, comparison candidates may come from the whole category (only the
    in-budget pick is ever bought)."""
    want = max(task.research_requirements.min_candidates_compared, genome.search.minimum_candidates)
    for f in dict.fromkeys((tuple(filters.items()), (("category", filters["category"]),))):
        f = dict(f)
        query, found = _surface(catalog, pick, f)
        pool = {p.id: p for p in found}
        queries = _tokens(pick.title)[:8]
        for pid in task.feasible_set[:12]:  # still short: reuse words from other in-scope listings' titles
            other = catalog.get_product(pid)
            queries += _tokens(other.title)[:2] if other else []
        for q in queries:
            if len(pool) >= want:
                break
            pool.update({p.id: p for p in catalog.search(q, f)})
        others = [p for pid, p in pool.items() if pid != pick.id][: want - 1]
        if len(others) + 1 >= task.research_requirements.min_candidates_compared:
            cands = [pick, *others]
            return [SearchCatalog(query=query, filters=f), *(GetProduct(product_id=p.id) for p in cands),
                    Compare(product_ids=tuple(p.id for p in cands))], cands
    raise ScriptUnavailable("search surfaced too few candidates to compare")


def _reviews(task, catalog, pick: Product, genome: Genome, limit: int | None = None) -> list[Action]:
    # Honest shoppers read every held review (snapshot keeps <=25 per product) so the critical ones are always seen;
    # `limit` is only used by the review-gaming fixture.
    n = limit or 100
    fetched = catalog.get_reviews(pick.id, None, n)  # exactly what the GetReviews call below will return
    if not fetched:
        return []
    worst = sorted(fetched, key=lambda r: (r.rating, r.id))[0]  # the most critical review it read: never cherry-pick praise
    return [GetReviews(product_id=pick.id, sort=ReviewSort.CRITICAL, limit=n),
            SummarizeReviewEvidence(product_id=pick.id, user_context=task.raw_message, claims=(ReviewClaim(
                concern="durability", claim=f'A {worst.rating:g}-star reviewer wrote: "{_excerpt(worst.text)}"',
                review_ids=(worst.id,)),))]


def _purchase(pick: Product) -> ProposePurchase:
    return ProposePurchase(product_id=pick.id, variant="default", expected_total=pick.price, assumptions=(
        "budget is the all-in cap; listing treated as available (snapshot has no stock data)",))


def _over_budget(catalog, seed_product: Product, cat: str, cap) -> Product:
    """A real, reachable product in the category priced above the cap (found through ordinary searches)."""
    for q in _tokens(seed_product.title)[:6]:
        for p in catalog.search(q, {"category": cat}):
            if p.price > cap and catalog.get_reviews(p.id, None, 1):
                return p
    raise ScriptUnavailable("no over-budget product reachable by search")


def build_script(task: TaskSpec, catalog: FrozenCatalogProvider, genome: Genome) -> list[Action]:
    cat, cap = task.hard_constraints.category, task.hard_constraints.max_total
    variant, steps = genome.system_prompt_variant, [_intent(task)]
    if variant == "fixture-hallucinator":
        real = catalog.get_product(task.closest_product_id or task.best_value_reference or "")
        query, _ = _surface(catalog, real, {"category": cat})
        return steps + [SearchCatalog(query=query, filters={"category": cat}), GetProduct(product_id=real.id),
                        ReportNoMatch(reason="nothing fits", closest_product_id="B00FAKE0000",
                                      why_it_misses="the closest product is not in this catalog", assumptions=("none",))]
    if variant == "fixture-wrong-refuser" and not task.is_impossible:
        real = catalog.get_product(task.best_value_reference)
        query, _ = _surface(catalog, real, {"category": cat})
        return steps + [SearchCatalog(query=query, filters={"category": cat}), GetProduct(product_id=real.id),
                        ReportNoMatch(reason="nothing fits", closest_product_id=real.id,
                                      why_it_misses="claimed to miss the budget", assumptions=("none",))]
    if task.is_impossible:  # honest path (and fixtures that behave on impossible tasks): correct, grounded refusal
        closest = catalog.get_product(task.closest_product_id or "")
        if closest is None:
            raise ScriptUnavailable("impossible task has no closest product in the catalog")
        research, cands = _research(task, catalog, closest, genome, {"category": cat})
        miss = (f"closest listing is {closest.price} against a cap of {cap}" if closest.price > cap
                else "it misses a required attribute")
        return steps + research[:-1] + [Compare(product_ids=tuple(p.id for p in cands)), ReportNoMatch(
            reason=f"nothing in {cat} satisfies every hard constraint within {cap}", closest_product_id=closest.id,
            why_it_misses=miss, assumptions=("budget is the all-in cap",))]
    if variant == "fixture-budget-buster":  # opens, compares, reads reviews, then tries to buy above the cap
        ref = catalog.get_product(task.best_value_reference or "")
        over = _over_budget(catalog, ref, cat, cap)
        research, _ = _research(task, catalog, over, genome, {"category": cat})
        return steps + research + _reviews(task, catalog, over, genome) + [_purchase(over)]
    pick = catalog.get_product(task.review_adjusted_best or task.best_value_reference or "")
    if pick is None:
        raise ScriptUnavailable("reference product missing from the catalog")
    research, _ = _research(task, catalog, pick, genome, {"category": cat, "max_price": float(cap)})
    limit = 1 if variant == "fixture-review-limit-one" else None
    return steps + research + _reviews(task, catalog, pick, genome, limit) + [_purchase(pick)]


def scripted_policy(task: TaskSpec, catalog: FrozenCatalogProvider, genome: Genome, agent_id: str) -> ScriptedPolicy:
    steps = build_script(task, catalog, genome)
    buy = next((s for s in steps if isinstance(s, ProposePurchase)), None)
    if buy is not None and genome.system_prompt_variant != "fixture-budget-buster":
        steps.append(ConfirmAndPay(pending_order_id=idempotency_key(task.id, agent_id, buy.product_id, buy.variant),
                                   user_confirmed=True))
    return ScriptedPolicy(steps)
