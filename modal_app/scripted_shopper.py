"""Scripted, NON-LLM shopper used to exercise the real pipeline (catalog -> runner -> scoring -> memory) end to end.

It has privileged catalog access (it reads the task's reference answer to choose what to buy), so its scores are an
integration check, NOT a model baseline and must never be reported as agent performance. Everything it submits is
grounded in real snapshot data: claims quote real review text verbatim and cite real review ids; nothing is invented."""
import re
from collections import Counter

from agents.actions import (Action, Compare, ConfirmAndPay, GetProduct, GetReviews, ParseIntent, ProposePurchase,
                            ReportNoMatch, SearchCatalog, SummarizeReviewEvidence)
from agents.runner import ScriptedPolicy
from catalog.providers.base import CatalogProvider, Product
from payments.guards import idempotency_key
from scoring.schemas import ReviewClaim, ReviewSort
from tasks.schemas import TaskSpec

_STOP = {"the", "and", "for", "with", "pack", "set", "inch", "men", "women", "of", "to", "in", "by", "a", "an", "new"}


class ScriptUnavailable(RuntimeError):
    """The catalog cannot support a grounded script for this task (reported, never papered over)."""


def _tokens(title: str) -> list[str]:
    words = [w for w in re.findall(r"[a-z]{3,}", title.lower()) if w not in _STOP]
    return [w for w, _ in Counter(words).most_common()]


def _find_query(catalog: CatalogProvider, target: Product, filters: dict) -> tuple[str, list[Product]]:
    """A real search query (taken from the target's own title) that actually surfaces the target."""
    toks = _tokens(target.title)
    for query in [" ".join(toks[:3]), " ".join(toks[:2]), *toks[:4]]:
        if not query:
            continue
        found = catalog.search(query, filters)
        if target.id in {p.id for p in found}:
            return query, found
    raise ScriptUnavailable(f"no search surfaces {target.id}")


def _excerpt(text: str, n: int = 160) -> str:
    text = re.sub(r"<[^>]+>|&[a-z]+;", " ", text)
    return " ".join(text.split())[:n].strip()


def build_script(task: TaskSpec, catalog: CatalogProvider, *, min_candidates: int = 2, review_limit: int = 2) -> list[Action]:
    cap = task.hard_constraints.max_total
    cat = task.hard_constraints.category
    steps: list[Action] = [ParseIntent(raw_message=task.raw_message, category=cat, max_total=cap,
                                       assumptions=("budget is the all-in cap; no size or stock constraint is assumed",))]
    if task.is_impossible:
        if not task.closest_product_id:
            raise ScriptUnavailable("impossible task has no closest product")
        closest = catalog.get_product(task.closest_product_id)
        if closest is None:
            raise ScriptUnavailable("closest product missing from catalog")
        query, found = _find_query(catalog, closest, {"category": cat})
        other = next((p for p in found if p.id != closest.id), None)
        if other is None:
            raise ScriptUnavailable("search surfaced no second candidate to compare")
        steps += [SearchCatalog(query=query, filters={"category": cat}), GetProduct(product_id=closest.id),
                  GetProduct(product_id=other.id), Compare(product_ids=(closest.id, other.id)),
                  ReportNoMatch(reason=f"nothing in {cat} satisfies every hard constraint within {cap}",
                                closest_product_id=closest.id,
                                why_it_misses=f"closest listing is {closest.price} against a cap of {cap}"
                                if closest.price > cap else "it misses a required attribute",
                                assumptions=("budget is the all-in cap",))]
        return steps
    pick = catalog.get_product(task.best_value_reference or "")
    if pick is None:
        raise ScriptUnavailable("best-value reference missing from catalog")
    filters = {"category": cat, "max_price": float(cap)}
    query, found = _find_query(catalog, pick, filters)
    others = [p for p in found if p.id != pick.id][: max(0, min_candidates - 1)]
    if len(others) + 1 < min_candidates:
        raise ScriptUnavailable("search surfaced too few candidates to compare")
    steps += [SearchCatalog(query=query, filters=filters)]
    steps += [GetProduct(product_id=p.id) for p in [pick, *others]]
    steps += [Compare(product_ids=tuple(p.id for p in [pick, *others]))]
    reviews = catalog.get_reviews(pick.id, None, 100)
    if reviews:  # read every held review, most critical first, so the cited one is genuinely the least favourable
        steps += [GetReviews(product_id=pick.id, sort=ReviewSort.CRITICAL, limit=min(100, max(review_limit, len(reviews))))]
        top = sorted(reviews, key=lambda r: (r.rating, r.id))[0]  # the most critical review: never cherry-pick praise
        steps += [SummarizeReviewEvidence(
            product_id=pick.id, user_context=task.raw_message,
            claims=(ReviewClaim(concern="durability", claim=f'A {top.rating:g}-star reviewer wrote: "{_excerpt(top.text)}"',
                                review_ids=(top.id,)),))]
    steps += [ProposePurchase(product_id=pick.id, variant="default", expected_total=pick.price,
                              assumptions=("budget is the all-in cap; listing treated as available (snapshot has no stock data)",))]
    return steps


def scripted_policy(task: TaskSpec, catalog: CatalogProvider, agent_id: str, **kw) -> ScriptedPolicy:
    steps = build_script(task, catalog, **kw)
    if any(isinstance(s, ProposePurchase) for s in steps):
        buy = next(s for s in steps if isinstance(s, ProposePurchase))
        steps.append(ConfirmAndPay(pending_order_id=idempotency_key(task.id, agent_id, buy.product_id, buy.variant),
                                   user_confirmed=True))
    return ScriptedPolicy(steps)
