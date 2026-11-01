"""Versioned, deterministic schemas for generated-task ground truth.

This module deliberately contains contracts only. Production tasks must later be
derived from a frozen catalog snapshot; no product or review data lives here.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


Identifier = Annotated[str, Field(min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")]
Money = Annotated[Decimal, Field(gt=0, decimal_places=2)]
Scalar = str | int | Decimal | bool


class ContractModel(BaseModel):
    """Strict immutable base so fixtures serialize and compare predictably."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ConstraintOperator(StrEnum):
    EQ = "eq"
    IN = "in"
    GTE = "gte"
    LTE = "lte"


class ReviewPolarity(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    MIXED = "mixed"


class SignalVerification(StrEnum):
    UNVERIFIED = "unverified"
    AUTOMATED = "automated_verified"
    HUMAN_APPROVED = "human_approved"
    REJECTED = "rejected"


class HumanReviewStatus(StrEnum):
    NOT_SAMPLED = "not_sampled"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ConstraintEvidence(ContractModel):
    """Whether and where a frozen catalog can verify a constraint."""

    checkable: bool
    source_field: str | None = Field(default=None, min_length=1)
    provenance: str = Field(min_length=1)

    @model_validator(mode="after")
    def checkable_constraints_need_a_field(self) -> ConstraintEvidence:
        if self.checkable and self.source_field is None:
            raise ValueError("checkable constraints require source_field")
        return self


class Difficulty(StrEnum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class TaskSplit(StrEnum):
    TRAIN = "train"
    VALIDATION = "val"
    TEST = "test"
    HELD_OUT_CATEGORY = "held_out_category"


class AttributeConstraint(ContractModel):
    attribute: Identifier
    operator: ConstraintOperator
    values: tuple[Scalar, ...] = Field(min_length=1)
    evidence: ConstraintEvidence = Field(
        default_factory=lambda: ConstraintEvidence(
            checkable=True,
            source_field="attributes",
            provenance="catalog product attribute",
        )
    )

    @model_validator(mode="after")
    def validate_operator_arity(self) -> AttributeConstraint:
        if self.operator is not ConstraintOperator.IN and len(self.values) != 1:
            raise ValueError(f"operator {self.operator} requires exactly one value")
        return self


class HardConstraints(ContractModel):
    category: Identifier
    max_total: Money
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    required_variant: str | None = Field(default=None, min_length=1)
    attributes: tuple[AttributeConstraint, ...] = ()
    category_evidence: ConstraintEvidence = Field(
        default_factory=lambda: ConstraintEvidence(
            checkable=True, source_field="category", provenance="catalog product category"
        )
    )
    price_evidence: ConstraintEvidence = Field(
        default_factory=lambda: ConstraintEvidence(
            checkable=True, source_field="price", provenance="catalog listed price"
        )
    )
    variant_evidence: ConstraintEvidence = Field(
        default_factory=lambda: ConstraintEvidence(
            checkable=True, source_field="variants", provenance="catalog variant inventory"
        )
    )

    @model_validator(mode="after")
    def reject_duplicate_attributes(self) -> HardConstraints:
        names = [constraint.attribute for constraint in self.attributes]
        if len(names) != len(set(names)):
            raise ValueError("hard-constraint attributes must be unique")
        return self


class ImpliedNeed(ContractModel):
    concern: Identifier
    attribute: Identifier | None = None
    acceptable_values: tuple[Scalar, ...] = ()
    weight: float = Field(default=1.0, gt=0, le=1)

    @model_validator(mode="after")
    def values_require_attribute(self) -> ImpliedNeed:
        if self.acceptable_values and self.attribute is None:
            raise ValueError("acceptable_values require a mapped attribute")
        return self


class Ambiguity(ContractModel):
    source_text: str = Field(min_length=1)
    acceptable_interpretations: tuple[str, ...] = Field(min_length=1)
    selected_interpretation: str = Field(min_length=1)

    @model_validator(mode="after")
    def selected_must_be_acceptable(self) -> Ambiguity:
        if self.selected_interpretation not in self.acceptable_interpretations:
            raise ValueError("selected_interpretation must be acceptable")
        return self


class ReviewSignal(ContractModel):
    concern: Identifier
    product_id: Identifier
    claim: str = Field(min_length=1)
    supporting_review_ids: tuple[Identifier, ...] = Field(min_length=1)
    persona_relevance: str = Field(default="general shopper", min_length=1)
    polarity: ReviewPolarity = ReviewPolarity.MIXED
    confidence: Decimal = Field(default=Decimal("1"), ge=0, le=1)
    extraction_provenance: str = Field(default="verified fixture", min_length=1)
    extraction_method: str = Field(default="legacy", min_length=1)
    extraction_version: str = Field(default="1", min_length=1)
    evidence_phrases: tuple[str, ...] = ()
    input_review_ids: tuple[Identifier, ...] = ()
    extracted_at: dt.datetime | None = None
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    verification_status: SignalVerification = SignalVerification.UNVERIFIED
    human_review_status: HumanReviewStatus = HumanReviewStatus.NOT_SAMPLED
    human_reviewer: str | None = Field(default=None, min_length=1)
    human_reviewed_at: dt.datetime | None = None
    human_review_notes: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def review_ids_must_be_unique(self) -> ReviewSignal:
        if len(self.supporting_review_ids) != len(set(self.supporting_review_ids)):
            raise ValueError("supporting_review_ids must be unique")
        if len(self.input_review_ids) != len(set(self.input_review_ids)):
            raise ValueError("input_review_ids must be unique")
        if self.input_review_ids and not set(self.supporting_review_ids) <= set(self.input_review_ids):
            raise ValueError("supporting reviews must be part of extractor input")
        verified = self.verification_status in {
            SignalVerification.AUTOMATED,
            SignalVerification.HUMAN_APPROVED,
        }
        if verified and (
            not self.input_review_ids
            or not self.evidence_phrases
            or self.extracted_at is None
            or self.content_hash is None
        ):
            raise ValueError("verified signals require evidence phrases, input IDs, extraction time, and content hash")
        if self.extracted_at is not None and self.extracted_at.tzinfo is None:
            raise ValueError("extracted_at must be timezone-aware")
        reviewed = self.human_review_status in {HumanReviewStatus.APPROVED, HumanReviewStatus.REJECTED}
        if reviewed and (self.human_reviewer is None or self.human_reviewed_at is None):
            raise ValueError("completed human review requires reviewer and timestamp")
        if self.human_reviewed_at is not None and self.human_reviewed_at.tzinfo is None:
            raise ValueError("human_reviewed_at must be timezone-aware")
        if self.human_review_status is HumanReviewStatus.APPROVED and self.verification_status is not SignalVerification.HUMAN_APPROVED:
            raise ValueError("approved human review must set human-approved verification")
        if self.human_review_status is HumanReviewStatus.REJECTED and self.verification_status is not SignalVerification.REJECTED:
            raise ValueError("rejected human review must reject the signal")
        return self


class ResearchRequirements(ContractModel):
    min_candidates_compared: int = Field(default=2, ge=1)
    min_reviews_consulted: int = Field(default=2, ge=1)


class TaskSpec(ContractModel):
    """Ground truth computed from one identified, frozen catalog snapshot."""

    schema_version: Literal["1.0"] = "1.0"
    id: Identifier
    catalog_snapshot_id: Identifier
    raw_message: str = Field(min_length=1)
    hard_constraints: HardConstraints
    implied_needs: tuple[ImpliedNeed, ...] = ()
    ambiguities: tuple[Ambiguity, ...] = ()
    feasible_set: tuple[Identifier, ...]
    best_value_reference: Identifier | None = None
    difficulty: Difficulty
    is_impossible: bool
    closest_product_id: Identifier | None = None
    review_signals: tuple[ReviewSignal, ...] = ()
    review_adjusted_best: Identifier | None = None
    is_review_trap: bool = False
    split: TaskSplit
    held_out_category: bool = False
    catalog_manifest_hash: str = Field(default="legacy-test-manifest", min_length=1)
    seed: int = Field(default=0, ge=0)
    suitable_for_deterministic_training: bool = True
    unsuitable_reasons: tuple[str, ...] = ()
    research_requirements: ResearchRequirements = Field(default_factory=ResearchRequirements)

    @model_validator(mode="after")
    def validate_ground_truth_links(self) -> TaskSpec:
        unchecked = []
        checks = (
            ("category", self.hard_constraints.category_evidence),
            ("price", self.hard_constraints.price_evidence),
        )
        for name, evidence in checks:
            if not evidence.checkable:
                unchecked.append(name)
        if self.hard_constraints.required_variant and not self.hard_constraints.variant_evidence.checkable:
            unchecked.append("variant")
        unchecked.extend(
            constraint.attribute
            for constraint in self.hard_constraints.attributes
            if not constraint.evidence.checkable
        )
        if len(self.feasible_set) != len(set(self.feasible_set)):
            raise ValueError("feasible_set must contain unique product ids")
        if unchecked:
            if self.suitable_for_deterministic_training or self.feasible_set or self.is_impossible:
                raise ValueError("uncheckable tasks must be unsuitable with unknown feasibility")
            if self.best_value_reference is not None or self.review_adjusted_best is not None:
                raise ValueError("uncheckable tasks cannot define a best product")
        elif self.is_impossible:
            if self.feasible_set:
                raise ValueError("impossible tasks cannot have feasible products")
            if self.best_value_reference is not None or self.review_adjusted_best is not None:
                raise ValueError("impossible tasks cannot define a best product")
            if self.closest_product_id is None:
                raise ValueError("impossible tasks require a closest real product")
        else:
            if not self.feasible_set:
                raise ValueError("is_impossible must be true when a suitable feasible_set is empty")
            if self.best_value_reference not in self.feasible_set:
                raise ValueError("best_value_reference must belong to feasible_set")
            if self.review_adjusted_best not in (None, *self.feasible_set):
                raise ValueError("review_adjusted_best must belong to feasible_set")
        if self.is_review_trap and (
            self.review_adjusted_best is None
            or self.review_adjusted_best == self.best_value_reference
            or not self.review_signals
        ):
            raise ValueError("review traps require signals and a distinct review-adjusted best")
        if self.held_out_category != (self.split is TaskSplit.HELD_OUT_CATEGORY):
            raise ValueError("held_out_category must match the held-out split")
        if bool(unchecked) == self.suitable_for_deterministic_training:
            raise ValueError("training suitability must reflect uncheckable hard constraints")
        if unchecked and not self.unsuitable_reasons:
            raise ValueError("uncheckable hard constraints require unsuitable_reasons")
        if not unchecked and self.unsuitable_reasons:
            raise ValueError("suitable tasks cannot have unsuitable_reasons")
        return self
