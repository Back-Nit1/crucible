"""Strict trace and scoring result contracts consumed by deterministic rules."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


Identifier = Annotated[str, Field(min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")]
Money = Annotated[Decimal, Field(gt=0, decimal_places=2)]
UnitScore = Annotated[Decimal, Field(ge=0, le=1)]
NonNegativeDecimal = Annotated[Decimal, Field(ge=0)]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ToolName(StrEnum):
    PARSE_INTENT = "parse_intent"
    SEARCH_CATALOG = "search_catalog"
    GET_PRODUCT = "get_product"
    COMPARE = "compare"
    GET_REVIEWS = "get_reviews"
    SUMMARIZE_REVIEW_EVIDENCE = "summarize_review_evidence"
    PROPOSE_PURCHASE = "propose_purchase"
    CONFIRM_AND_PAY = "confirm_and_pay"
    REPORT_NO_MATCH = "report_no_match"


class ReviewSort(StrEnum):
    RELEVANT = "relevant"
    RECENT = "recent"
    CRITICAL = "critical"


class ToolCall(ContractModel):
    sequence: int = Field(ge=0)
    name: ToolName
    product_id: Identifier | None = None
    product_ids: tuple[Identifier, ...] = ()
    review_ids: tuple[Identifier, ...] = ()
    review_focus: str | None = Field(default=None, min_length=1)
    review_sort: ReviewSort | None = None
    limit: int | None = Field(default=None, ge=1)
    variant: str | None = Field(default=None, min_length=1)
    amount: Money | None = None
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    idempotency_key: Identifier | None = None

    @model_validator(mode="after")
    def validate_action_fields(self) -> ToolCall:
        single_product_actions = {
            ToolName.GET_PRODUCT,
            ToolName.GET_REVIEWS,
            ToolName.SUMMARIZE_REVIEW_EVIDENCE,
            ToolName.PROPOSE_PURCHASE,
        }
        if self.name in single_product_actions and self.product_id is None:
            raise ValueError(f"{self.name} requires product_id")
        if self.name is ToolName.COMPARE and len(self.product_ids) < 2:
            raise ValueError("compare requires at least two product ids")
        if self.name is ToolName.GET_REVIEWS and (self.limit is None or self.review_sort is None):
            raise ValueError("get_reviews requires limit and review_sort")
        if self.name is ToolName.PROPOSE_PURCHASE and (
            self.variant is None
            or self.amount is None
            or self.currency is None
            or self.idempotency_key is None
        ):
            raise ValueError("propose_purchase requires variant, amount, currency, and idempotency_key")
        return self


class ReviewClaim(ContractModel):
    concern: Identifier | None = None
    claim: str = Field(min_length=1)
    review_ids: tuple[Identifier, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def review_ids_must_be_unique(self) -> ReviewClaim:
        if len(self.review_ids) != len(set(self.review_ids)):
            raise ValueError("review_ids must be unique")
        return self


class Recommendation(ContractModel):
    product_id: Identifier
    variant: str = Field(min_length=1)
    expected_total: Money
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    review_claims: tuple[ReviewClaim, ...] = ()


class RecommendationOutcome(ContractModel):
    kind: Literal["recommendation"] = "recommendation"
    recommendations: tuple[Recommendation, ...] = Field(min_length=1, max_length=3)
    assumptions: tuple[str, ...] = ()


class NoMatchOutcome(ContractModel):
    kind: Literal["no_match"] = "no_match"
    reason: str = Field(min_length=1)
    closest_product_id: Identifier
    why_it_misses: str = Field(min_length=1)
    assumptions: tuple[str, ...] = ()


class PaymentStatus(StrEnum):
    ATTEMPTED = "attempted"
    FAILED = "failed"
    COMPLETED = "completed"


class PaymentEvent(ContractModel):
    sequence: int = Field(ge=0)
    product_id: Identifier
    variant: str = Field(min_length=1)
    amount: Money
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    idempotency_key: Identifier
    status: PaymentStatus
    order_id: Identifier | None = None
    capture_id: Identifier | None = None

    @model_validator(mode="after")
    def completed_payment_has_ledger_ids(self) -> PaymentEvent:
        if self.status is PaymentStatus.COMPLETED and (
            self.order_id is None or self.capture_id is None
        ):
            raise ValueError("completed payments require order_id and capture_id")
        return self


Outcome = RecommendationOutcome | NoMatchOutcome


class EpisodeTrace(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    task_id: Identifier
    catalog_snapshot_id: Identifier
    tool_calls: tuple[ToolCall, ...]
    outcome: Outcome = Field(discriminator="kind")
    payments: tuple[PaymentEvent, ...] = ()

    @model_validator(mode="after")
    def sequences_must_be_strictly_increasing(self) -> EpisodeTrace:
        tool_sequences = [call.sequence for call in self.tool_calls]
        payment_sequences = [event.sequence for event in self.payments]
        if tool_sequences != sorted(set(tool_sequences)):
            raise ValueError("tool-call sequence numbers must be unique and increasing")
        if payment_sequences != sorted(set(payment_sequences)):
            raise ValueError("payment sequence numbers must be unique and increasing")
        return self


class GateViolationCode(StrEnum):
    WRONG_REFUSAL = "wrong_refusal"
    INVALID_CLOSEST_PRODUCT = "invalid_closest_product"
    PRODUCT_NOT_FOUND = "product_not_found"
    CATEGORY_MISMATCH = "category_mismatch"
    OUT_OF_STOCK = "out_of_stock"
    OVER_BUDGET = "over_budget"
    NOT_IN_FEASIBLE_SET = "not_in_feasible_set"


class GateViolation(ContractModel):
    code: GateViolationCode
    product_id: Identifier | None = None
    detail: str = Field(min_length=1)


class GateResult(ContractModel):
    value: Literal[0, 1]
    violations: tuple[GateViolation, ...] = ()

    @model_validator(mode="after")
    def value_matches_violations(self) -> GateResult:
        if self.value != int(not self.violations):
            raise ValueError("gate value must be 1 exactly when violations are empty")
        return self


class KillDecision(ContractModel):
    rule_id: Identifier
    rule_version: int = Field(ge=1)
    description: str = Field(min_length=1)
    evidence: tuple[str, ...] = Field(min_length=1)


class KillEvaluation(ContractModel):
    killed: bool
    decisions: tuple[KillDecision, ...] = ()

    @model_validator(mode="after")
    def killed_matches_decisions(self) -> KillEvaluation:
        if self.killed != bool(self.decisions):
            raise ValueError("killed must reflect whether any rule fired")
        return self


class QualityMetricName(StrEnum):
    IMPLIED_NEEDS_FIT = "implied_needs_fit"
    VALUE = "value"
    INTENT_EXTRACTION = "intent_extraction"
    REVIEWS_CONSULTED = "reviews_consulted"
    REVIEW_GROUNDING = "review_grounding"
    REVIEW_SIGNAL_RECALL = "review_signal_recall"
    REVIEW_ADJUSTED_CHOICE = "review_adjusted_choice"
    ASSUMPTIONS = "assumptions"


class QualityMetric(ContractModel):
    name: QualityMetricName
    value: UnitScore
    weight: Annotated[Decimal, Field(gt=0)]
    evidence: tuple[str, ...] = Field(min_length=1)


class QualityAssessment(ContractModel):
    """Auditable Q inputs; policy owners supply explicit versioned weights."""

    metrics: tuple[QualityMetric, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def metric_names_must_be_unique(self) -> QualityAssessment:
        names = [metric.name for metric in self.metrics]
        if len(names) != len(set(names)):
            raise ValueError("quality metric names must be unique")
        return self


class ScoreResult(ContractModel):
    gate: Literal[0, 1]
    quality: UnitScore
    efficiency_penalty: NonNegativeDecimal
    fitness: Decimal
