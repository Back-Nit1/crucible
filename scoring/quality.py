"""Composable deterministic quality metrics with explicit evidence and weights."""

from __future__ import annotations

from decimal import Decimal

from catalog.providers.base import FrozenCatalogProvider
from scoring.schemas import (
    EpisodeTrace, NoMatchOutcome, QualityAssessment, QualityMetric, QualityMetricName,
    RecommendationOutcome, ToolName,
)
from tasks.schemas import TaskSpec


DEFAULT_WEIGHTS: dict[QualityMetricName, Decimal] = {
    name: Decimal("1") for name in QualityMetricName
}


def _metric(name: QualityMetricName, value: Decimal, evidence: str,
            weights: dict[QualityMetricName, Decimal]) -> QualityMetric:
    return QualityMetric(name=name, value=max(Decimal(0), min(Decimal(1), value)),
                         weight=weights[name], evidence=(evidence,))


def assess_quality(
    task: TaskSpec, trace: EpisodeTrace, catalog: FrozenCatalogProvider, *,
    intent_accuracy: Decimal = Decimal("1"), assumption_accuracy: Decimal | None = None,
    weights: dict[QualityMetricName, Decimal] | None = None,
) -> QualityAssessment:
    weights = weights or DEFAULT_WEIGHTS
    missing = set(QualityMetricName) - set(weights)
    if missing:
        raise ValueError(f"missing quality weights: {sorted(missing)}")
    calls = trace.tool_calls
    reviewed = {call.product_id: set(call.review_ids) for call in calls if call.name is ToolName.GET_REVIEWS}
    compared = {pid for call in calls if call.name is ToolName.COMPARE for pid in call.product_ids}
    opened = {call.product_id for call in calls if call.name is ToolName.GET_PRODUCT}
    metrics = [_metric(QualityMetricName.INTENT_EXTRACTION, intent_accuracy,
                       "caller-supplied deterministic intent field comparison", weights)]

    assumptions = trace.outcome.assumptions
    assumption_score = assumption_accuracy if assumption_accuracy is not None else Decimal(bool(assumptions))
    metrics.append(_metric(QualityMetricName.ASSUMPTIONS, assumption_score,
                           "assumptions present and externally checked when supplied", weights))

    if isinstance(trace.outcome, NoMatchOutcome):
        correct = not task.feasible_set and trace.outcome.closest_product_id == task.closest_product_id
        score = Decimal(correct)
        for name in QualityMetricName:
            if name in {QualityMetricName.INTENT_EXTRACTION, QualityMetricName.ASSUMPTIONS}:
                continue
            value = score if name is QualityMetricName.NO_MATCH_QUALITY else Decimal("1")
            metrics.append(_metric(name, value, "deterministic impossible-task outcome", weights))
        return QualityAssessment(metrics=tuple(metrics))

    recommendations = trace.outcome.recommendations
    products = [catalog.get_product(item.product_id) for item in recommendations]
    mapped_needs = [need for need in task.implied_needs if need.attribute and need.acceptable_values]
    if mapped_needs and products:
        hits = sum(product is not None and product.attributes.get(need.attribute) in need.acceptable_values
                   for product in products for need in mapped_needs)
        need_score = Decimal(hits) / Decimal(len(products) * len(mapped_needs))
    else:
        need_score = Decimal("1")
    metrics.append(_metric(QualityMetricName.IMPLIED_NEEDS_FIT, need_score,
                           "catalog attributes matched mapped implied needs", weights))

    selected_ids = {item.product_id for item in recommendations}
    value = Decimal(task.best_value_reference in selected_ids) if task.best_value_reference else Decimal(0)
    metrics.append(_metric(QualityMetricName.VALUE, value, "selection compared with best-value reference", weights))
    consulted = Decimal(all(not catalog.get_reviews(pid, limit=1) or reviewed.get(pid) for pid in selected_ids))
    metrics.append(_metric(QualityMetricName.REVIEWS_CONSULTED, consulted,
                           "selected products with reviews have review calls", weights))

    cited_pairs = [(item.product_id, rid) for item in recommendations
                   for claim in item.review_claims for rid in claim.review_ids]
    valid_pairs = {(pid, rid) for pid in selected_ids for rid in catalog.get_review_ids(pid).ids}
    grounded = Decimal(sum(pair in valid_pairs for pair in cited_pairs)) / Decimal(len(cited_pairs)) if cited_pairs else Decimal(1)
    metrics.append(_metric(QualityMetricName.REVIEW_GROUNDING, grounded,
                           "review citations checked against product-scoped IDs", weights))
    metrics.append(_metric(QualityMetricName.REVIEW_ID_EXISTENCE, grounded,
                           "all cited IDs checked for existence", weights))

    expected_signals = {(signal.product_id, rid) for signal in task.review_signals for rid in signal.supporting_review_ids}
    cited = set(cited_pairs)
    recall = Decimal(len(expected_signals & cited)) / Decimal(len(expected_signals)) if expected_signals else Decimal(1)
    metrics.append(_metric(QualityMetricName.REVIEW_SIGNAL_RECALL, recall,
                           "persona-relevant signal IDs recalled", weights))
    trap = Decimal(not task.is_review_trap or task.review_adjusted_best in selected_ids)
    metrics.append(_metric(QualityMetricName.REVIEW_ADJUSTED_CHOICE, trap,
                           "review-adjusted best selected when task is a trap", weights))
    metrics.append(_metric(QualityMetricName.REVIEW_TRAP_CHOICE, trap,
                           "review trap choice checked", weights))
    required = min(task.research_requirements.min_candidates_compared, len(task.feasible_set))
    sufficient = Decimal(selected_ids <= opened and len(compared) >= required)
    metrics.append(_metric(QualityMetricName.RESEARCH_SUFFICIENCY, sufficient,
                           "detail-open and comparison counts checked", weights))
    metrics.append(_metric(QualityMetricName.NO_MATCH_QUALITY, Decimal("1"),
                           "not applicable to recommendation outcome", weights))
    return QualityAssessment(metrics=tuple(metrics))
