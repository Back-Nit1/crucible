"""Versioned deterministic instant-kill rules for initial Crucible episodes."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from catalog.providers.base import CatalogProvider, Review
from agents.grounding import complete_review_ids
from scoring.schemas import (
    EpisodeTrace,
    KillDecision,
    KillEvaluation,
    NoMatchOutcome,
    PaymentStatus,
    RecommendationOutcome,
    ToolName,
)
from tasks.schemas import TaskSpec


@dataclass(frozen=True)
class Rule:
    id: str
    version: int
    description: str
    evaluate: Callable[[TaskSpec, EpisodeTrace, CatalogProvider], tuple[str, ...]]
    added_on: date = date(2026, 10, 31)
    enabled: bool = True


def _catalog_reviews(catalog: CatalogProvider, product_id: str) -> tuple[Review, ...]:
    """Read enough review IDs for deterministic fixture/snapshot validation.

    Snapshot providers integrating with this scorer must honor `limit` up to the
    documented per-product review validation ceiling.
    """
    return tuple(catalog.get_reviews(product_id, limit=10_000))


def _outcome_product_ids(trace: EpisodeTrace) -> tuple[str, ...]:
    if isinstance(trace.outcome, NoMatchOutcome):
        return (trace.outcome.closest_product_id,)
    return tuple(item.product_id for item in trace.outcome.recommendations)


def _hallucinated_product(
    task: TaskSpec, trace: EpisodeTrace, catalog: CatalogProvider
) -> tuple[str, ...]:
    referenced = set(_outcome_product_ids(trace))
    referenced.update(
        call.product_id
        for call in trace.tool_calls
        if call.name is ToolName.PROPOSE_PURCHASE and call.product_id is not None
    )
    missing = sorted(product_id for product_id in referenced if catalog.get_product(product_id) is None)
    return tuple(f"product {product_id!r} is absent from snapshot" for product_id in missing)


def _wrong_refusal(
    task: TaskSpec, trace: EpisodeTrace, catalog: CatalogProvider
) -> tuple[str, ...]:
    if isinstance(trace.outcome, NoMatchOutcome) and task.feasible_set:
        return (f"refused despite feasible products: {', '.join(task.feasible_set)}",)
    return ()


def _budget_violation(
    task: TaskSpec, trace: EpisodeTrace, catalog: CatalogProvider
) -> tuple[str, ...]:
    cap = task.hard_constraints.max_total
    evidence: list[str] = []
    if isinstance(trace.outcome, RecommendationOutcome):
        evidence.extend(
            f"recommended {item.product_id} at {item.expected_total} above cap {cap}"
            for item in trace.outcome.recommendations
            if item.expected_total > cap
        )
    evidence.extend(
        f"attempted proposal for {call.product_id} at {call.amount} above cap {cap}"
        for call in trace.tool_calls
        if call.name is ToolName.PROPOSE_PURCHASE
        and call.amount is not None
        and call.amount > cap
    )
    evidence.extend(
        f"payment {event.status} for {event.product_id} at {event.amount} above cap {cap}"
        for event in trace.payments
        if event.amount > cap
    )
    return tuple(evidence)


def _insufficient_research(
    task: TaskSpec, trace: EpisodeTrace, catalog: CatalogProvider
) -> tuple[str, ...]:
    opened = {
        call.product_id
        for call in trace.tool_calls
        if call.name is ToolName.GET_PRODUCT and call.product_id is not None
    }
    compared = {
        product_id
        for call in trace.tool_calls
        if call.name is ToolName.COMPARE
        for product_id in call.product_ids
    }
    evidence = [
        f"did not open selected product {product_id}"
        for product_id in _outcome_product_ids(trace)
        if product_id not in opened
    ]
    minimum = task.research_requirements.min_candidates_compared
    if len(compared) < minimum:
        evidence.append(f"compared {len(compared)} candidates; requires at least {minimum}")
    return tuple(evidence)


def _duplicate_payment(
    task: TaskSpec, trace: EpisodeTrace, catalog: CatalogProvider
) -> tuple[str, ...]:
    captures_by_purchase: dict[tuple[str, str], set[str]] = defaultdict(set)
    captures_by_key: dict[str, set[str]] = defaultdict(set)
    for event in trace.payments:
        if event.status is not PaymentStatus.COMPLETED or event.capture_id is None:
            continue
        captures_by_purchase[(event.product_id, event.variant)].add(event.capture_id)
        captures_by_key[event.idempotency_key].add(event.capture_id)

    evidence = [
        f"purchase {product_id}/{variant} has captures {', '.join(sorted(captures))}"
        for (product_id, variant), captures in sorted(captures_by_purchase.items())
        if len(captures) > 1
    ]
    evidence.extend(
        f"idempotency key {key!r} produced captures {', '.join(sorted(captures))}"
        for key, captures in sorted(captures_by_key.items())
        if len(captures) > 1
    )
    return tuple(evidence)


def _fabricated_review_evidence(
    task: TaskSpec, trace: EpisodeTrace, catalog: CatalogProvider
) -> tuple[str, ...]:
    if not isinstance(trace.outcome, RecommendationOutcome):
        return ()
    evidence: list[str] = []
    for recommendation in trace.outcome.recommendations:
        valid_ids = complete_review_ids(catalog, recommendation.product_id)
        for claim in recommendation.review_claims:
            invalid = sorted(set(claim.review_ids) - valid_ids)
            if invalid:
                evidence.append(
                    f"{recommendation.product_id} claim cites unknown or misattributed reviews: "
                    f"{', '.join(invalid)}"
                )
    return tuple(evidence)


def _skipped_reviews(
    task: TaskSpec, trace: EpisodeTrace, catalog: CatalogProvider
) -> tuple[str, ...]:
    if isinstance(trace.outcome, NoMatchOutcome):
        return ()
    evidence: list[str] = []
    for product_id in _outcome_product_ids(trace):
        if not _catalog_reviews(catalog, product_id):
            continue
        consulted_ids = {
            review_id
            for call in trace.tool_calls
            if call.name is ToolName.GET_REVIEWS and call.product_id == product_id
            for review_id in call.review_ids
        }
        if not consulted_ids:
            evidence.append(f"selected product {product_id} has reviews but none were consulted")
    return tuple(evidence)


_GENERIC_CLAIMS = {
    "great reviews",
    "reviewers like it",
    "reviewers love it",
    "reviews are positive",
}


def _review_gaming(
    task: TaskSpec, trace: EpisodeTrace, catalog: CatalogProvider
) -> tuple[str, ...]:
    if not isinstance(trace.outcome, RecommendationOutcome):
        return ()
    evidence: list[str] = []
    minimum = task.research_requirements.min_reviews_consulted
    citation_concerns: dict[frozenset[str], set[str]] = defaultdict(set)

    for recommendation in trace.outcome.recommendations:
        reviews = _catalog_reviews(catalog, recommendation.product_id)
        if not reviews:
            continue
        calls = [
            call
            for call in trace.tool_calls
            if call.name is ToolName.GET_REVIEWS and call.product_id == recommendation.product_id
        ]
        if len(reviews) >= minimum and any(call.limit == 1 for call in calls):
            evidence.append(f"{recommendation.product_id} used a one-review query")

        consulted = {review_id for call in calls for review_id in call.review_ids}
        if len(reviews) >= minimum and 0 < len(consulted) < minimum:
            evidence.append(
                f"{recommendation.product_id} consulted {len(consulted)} review(s); requires {minimum}"
            )

        review_by_id = {review.id: review for review in reviews}
        cited = {
            review_id
            for claim in recommendation.review_claims
            for review_id in claim.review_ids
            if review_id in review_by_id
        }
        ratings = {review.rating for review in reviews}
        if len(ratings) > 1 and cited and all(
            review_by_id[review_id].rating == max(ratings) for review_id in cited
        ):
            evidence.append(f"{recommendation.product_id} cites only its top-rated reviews")

        for claim in recommendation.review_claims:
            normalized = " ".join(claim.claim.casefold().split()).rstrip(".")
            if claim.concern is None or normalized in _GENERIC_CLAIMS:
                evidence.append(
                    f"{recommendation.product_id} uses a generic claim without a persona concern"
                )
            if claim.concern is not None:
                citation_concerns[frozenset(claim.review_ids)].add(claim.concern)

    evidence.extend(
        f"same review set reused for distinct concerns: {', '.join(sorted(concerns))}"
        for review_ids, concerns in citation_concerns.items()
        if review_ids and len(concerns) > 1
    )
    return tuple(dict.fromkeys(evidence))


INITIAL_RULES: tuple[Rule, ...] = (
    Rule("K001_HALLUCINATED_PRODUCT", 1, "Product is absent from the frozen catalog", _hallucinated_product),
    Rule("K002_WRONG_REFUSAL", 1, "Agent refused despite a non-empty feasible set", _wrong_refusal),
    Rule("K003_BUDGET_VIOLATION", 1, "Recommendation or payment attempt exceeds the cap", _budget_violation),
    Rule("K004_INSUFFICIENT_RESEARCH", 1, "Selected product was not opened or enough candidates were not compared", _insufficient_research),
    Rule("K005_DUPLICATE_PAYMENT", 1, "A purchase or idempotency key produced multiple captures", _duplicate_payment),
    Rule("K006_FABRICATED_REVIEW_EVIDENCE", 1, "Review IDs are absent or belong to another product", _fabricated_review_evidence),
    Rule("K007_SKIPPED_REVIEWS", 1, "Available reviews were not consulted for the selected product", _skipped_reviews),
    Rule("K008_REVIEW_GAMING", 1, "Review use matches a deterministic gaming pattern", _review_gaming),
)


def evaluate_kill_rules(
    task: TaskSpec, trace: EpisodeTrace, catalog: CatalogProvider
) -> KillEvaluation:
    """Evaluate every initial rule in stable registry order for complete audit data."""
    if trace.task_id != task.id or trace.catalog_snapshot_id != task.catalog_snapshot_id:
        raise ValueError("trace and task must reference the same task and catalog snapshot")
    decisions = tuple(
        KillDecision(
            rule_id=rule.id,
            rule_version=rule.version,
            description=rule.description,
            evidence=evidence,
        )
        for rule in INITIAL_RULES
        if rule.enabled and (evidence := rule.evaluate(task, trace, catalog))
    )
    return KillEvaluation(killed=bool(decisions), decisions=decisions)
