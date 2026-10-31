"""Versioned review-signal extraction with deterministic lexical grounding."""

from __future__ import annotations

import datetime as dt
import hashlib
import html
import json
import re
from dataclasses import dataclass
from decimal import Decimal

from catalog.providers.base import Review, SnapshotCatalog
from pydantic import Field

from tasks.schemas import (
    ContractModel,
    HumanReviewStatus,
    ReviewPolarity,
    ReviewSignal,
    SignalVerification,
)

LEXICAL_METHOD = "literal_phrase_baseline"
LEXICAL_VERSION = "1.0"


class LexicalRule(ContractModel):
    concern: str = Field(min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    phrases: tuple[str, ...] = Field(min_length=1)
    persona_relevance: str = Field(min_length=1)
    polarity: ReviewPolarity
    minimum_support: int = Field(default=1, ge=1)
    maximum_support: int = Field(default=5, ge=1)


@dataclass(frozen=True)
class ExtractionResult:
    product_id: str
    input_review_ids: tuple[str, ...]
    signals: tuple[ReviewSignal, ...]


def _normalize(text: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", html.unescape(text))
    return " ".join(without_tags.casefold().split())


def _content_hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _load_complete_reviews(catalog: SnapshotCatalog, product_id: str) -> tuple[Review, ...]:
    expected_ids = catalog.review_ids(product_id)
    count = catalog.review_count(product_id)
    if count != len(expected_ids):
        raise ValueError("review count and complete ID lookup disagree")
    reviews = tuple(catalog.get_reviews(product_id, limit=max(count, 1)))
    found = {review.id for review in reviews}
    if found != set(expected_ids) or len(found) != len(reviews):
        raise ValueError("review text retrieval is incomplete or contains duplicate IDs")
    if any(review.product_id != product_id for review in reviews):
        raise ValueError("cross-product review returned by snapshot")
    return tuple(sorted(reviews, key=lambda review: review.id))


def extract_lexical_signals(
    catalog: SnapshotCatalog,
    product_id: str,
    rules: tuple[LexicalRule, ...],
    *,
    extracted_at: dt.datetime,
) -> ExtractionResult:
    """Extract only literal phrases present in canonical product-scoped reviews."""
    if extracted_at.tzinfo is None:
        raise ValueError("extracted_at must be timezone-aware")
    reviews = _load_complete_reviews(catalog, product_id)
    input_ids = tuple(review.id for review in reviews)
    normalized = {review.id: _normalize(review.text) for review in reviews}
    signals: list[ReviewSignal] = []
    for rule in rules:
        phrases = tuple(dict.fromkeys(_normalize(phrase) for phrase in rule.phrases if _normalize(phrase)))
        matches = [
            review.id
            for review in reviews
            if any(phrase in normalized[review.id] for phrase in phrases)
        ]
        if len(matches) < rule.minimum_support:
            continue
        cited = tuple(matches[: rule.maximum_support])
        supported_phrases = tuple(
            phrase for phrase in phrases if any(phrase in normalized[review_id] for review_id in cited)
        )
        claim = "Review text literally contains: " + "; ".join(
            f'"{phrase}"' for phrase in supported_phrases
        )
        payload = {
            "method": LEXICAL_METHOD,
            "version": LEXICAL_VERSION,
            "product_id": product_id,
            "input": [
                {"id": review.id, "text_hash": hashlib.sha256(review.text.encode()).hexdigest()}
                for review in reviews
            ],
            "concern": rule.concern,
            "claim": claim,
            "cited": cited,
            "phrases": supported_phrases,
        }
        signals.append(
            ReviewSignal(
                concern=rule.concern,
                product_id=product_id,
                claim=claim,
                supporting_review_ids=cited,
                persona_relevance=rule.persona_relevance,
                polarity=rule.polarity,
                confidence=min(Decimal("1"), Decimal(len(cited)) / Decimal(rule.minimum_support + 1)),
                extraction_provenance="deterministic literal phrase match against canonical review text",
                extraction_method=LEXICAL_METHOD,
                extraction_version=LEXICAL_VERSION,
                evidence_phrases=supported_phrases,
                input_review_ids=input_ids,
                extracted_at=extracted_at,
                content_hash=_content_hash(payload),
                verification_status=SignalVerification.AUTOMATED,
                human_review_status=HumanReviewStatus.NOT_SAMPLED,
            )
        )
    return ExtractionResult(product_id, input_ids, tuple(signals))


def validate_signal_text(signal: ReviewSignal, catalog: SnapshotCatalog) -> None:
    """Fail closed if IDs move products or cited text lacks the recorded phrase."""
    reviews = _load_complete_reviews(catalog, signal.product_id)
    by_id = {review.id: review for review in reviews}
    if not set(signal.supporting_review_ids) <= set(by_id):
        raise ValueError("signal cites a nonexistent or cross-product review")
    for phrase in signal.evidence_phrases:
        if not any(_normalize(phrase) in _normalize(by_id[review_id].text) for review_id in signal.supporting_review_ids):
            raise ValueError("signal claim is unsupported by cited review text")


def record_human_review(
    signal: ReviewSignal,
    *,
    approved: bool,
    reviewer: str,
    reviewed_at: dt.datetime,
    notes: str,
) -> ReviewSignal:
    """Record sampled review status without relabelling untouched signals."""
    status = HumanReviewStatus.APPROVED if approved else HumanReviewStatus.REJECTED
    verification = SignalVerification.HUMAN_APPROVED if approved else SignalVerification.REJECTED
    return ReviewSignal.model_validate(
        {
            **signal.model_dump(),
            "human_review_status": status,
            "verification_status": verification,
            "human_reviewer": reviewer,
            "human_reviewed_at": reviewed_at,
            "human_review_notes": notes,
        }
    )
