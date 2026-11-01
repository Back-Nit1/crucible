import datetime as dt

import pytest

from catalog.providers.base import Review
from tasks.review_signals import (
    LexicalRule,
    extract_lexical_signals,
    record_human_review,
    validate_signal_text,
)
from tasks.schemas import HumanReviewStatus, ReviewPolarity, SignalVerification
from tests.fixtures.scoring import InMemoryCatalog


NOW = dt.datetime(2026, 10, 31, 12, 0, tzinfo=dt.UTC)


def rule(**changes):
    values = {
        "concern": "cushioning",
        "phrases": ("cushioning remained supportive",),
        "persona_relevance": "runner seeking support",
        "polarity": ReviewPolarity.POSITIVE,
    }
    values.update(changes)
    return LexicalRule(**values)


def test_lexical_extractor_records_versioned_grounded_provenance():
    catalog = InMemoryCatalog()
    result = extract_lexical_signals(catalog, "shoe-a", (rule(),), extracted_at=NOW)
    assert result.input_review_ids == ("review-a-critical", "review-a-positive")
    signal = result.signals[0]
    assert signal.supporting_review_ids == ("review-a-positive",)
    assert signal.verification_status is SignalVerification.AUTOMATED
    assert signal.human_review_status is HumanReviewStatus.NOT_SAMPLED
    assert signal.extraction_method == "literal_phrase_baseline"
    assert signal.extraction_version == "1.0"
    assert len(signal.content_hash or "") == 64
    validate_signal_text(signal, catalog)


def test_ratings_alone_and_absent_phrases_create_no_signal():
    result = extract_lexical_signals(
        InMemoryCatalog(),
        "shoe-a",
        (rule(phrases=("perfect for every runner",)),),
        extracted_at=NOW,
    )
    assert result.signals == ()


def test_cross_product_review_return_fails_closed():
    catalog = InMemoryCatalog()
    catalog.reviews["shoe-a"] = (
        Review(
            id="foreign",
            product_id="shoe-b",
            rating=5,
            text="cushioning remained supportive",
        ),
    )
    with pytest.raises(ValueError, match="cross-product"):
        extract_lexical_signals(catalog, "shoe-a", (rule(),), extracted_at=NOW)


def test_unsupported_signal_text_is_rejected_after_source_changes():
    catalog = InMemoryCatalog()
    signal = extract_lexical_signals(catalog, "shoe-a", (rule(),), extracted_at=NOW).signals[0]
    catalog.reviews["shoe-a"] = tuple(
        review.model_copy(update={"text": "text no longer contains the evidence"})
        for review in catalog.reviews["shoe-a"]
    )
    with pytest.raises(ValueError, match="unsupported"):
        validate_signal_text(signal, catalog)


def test_human_review_status_is_explicit_and_not_implied():
    signal = extract_lexical_signals(InMemoryCatalog(), "shoe-a", (rule(),), extracted_at=NOW).signals[0]
    approved = record_human_review(
        signal,
        approved=True,
        reviewer="reviewer-1",
        reviewed_at=NOW + dt.timedelta(hours=1),
        notes="Literal phrase checked against cited review.",
    )
    assert approved.human_review_status is HumanReviewStatus.APPROVED
    assert approved.verification_status is SignalVerification.HUMAN_APPROVED
    assert signal.human_review_status is HumanReviewStatus.NOT_SAMPLED
