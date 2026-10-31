"""Strict, serializable action and episode contracts for model-independent agents."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scoring.schemas import ReviewClaim, ReviewSort


class ActionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ParseIntent(ActionModel):
    type: Literal["parse_intent"] = "parse_intent"
    raw_message: str = Field(min_length=1)
    category: str = Field(min_length=1)
    max_total: Decimal = Field(gt=0, decimal_places=2)
    assumptions: tuple[str, ...] = Field(min_length=1)


class SearchCatalog(ActionModel):
    type: Literal["search_catalog"] = "search_catalog"
    query: str
    filters: dict[str, object] = Field(default_factory=dict)


class GetProduct(ActionModel):
    type: Literal["get_product"] = "get_product"
    product_id: str = Field(min_length=1)


class Compare(ActionModel):
    type: Literal["compare"] = "compare"
    product_ids: tuple[str, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def unique_products(self) -> Compare:
        if len(self.product_ids) != len(set(self.product_ids)):
            raise ValueError("compare product_ids must be unique")
        return self


class GetReviews(ActionModel):
    type: Literal["get_reviews"] = "get_reviews"
    product_id: str = Field(min_length=1)
    focus: str | None = Field(default=None, min_length=1)
    sort: ReviewSort = ReviewSort.RELEVANT
    limit: int = Field(default=10, ge=1, le=100)


class SummarizeReviewEvidence(ActionModel):
    type: Literal["summarize_review_evidence"] = "summarize_review_evidence"
    product_id: str = Field(min_length=1)
    user_context: str = Field(min_length=1)
    claims: tuple[ReviewClaim, ...] = Field(min_length=1)


class ProposePurchase(ActionModel):
    type: Literal["propose_purchase"] = "propose_purchase"
    product_id: str = Field(min_length=1)
    variant: str = Field(min_length=1)
    expected_total: Decimal = Field(gt=0, decimal_places=2)
    assumptions: tuple[str, ...] = Field(min_length=1)


class ConfirmAndPay(ActionModel):
    type: Literal["confirm_and_pay"] = "confirm_and_pay"
    pending_order_id: str = Field(min_length=1)
    user_confirmed: bool


class ReportNoMatch(ActionModel):
    type: Literal["report_no_match"] = "report_no_match"
    reason: str = Field(min_length=1)
    closest_product_id: str | None = None
    why_it_misses: str = Field(min_length=1)
    assumptions: tuple[str, ...] = Field(min_length=1)


Action = Annotated[
    ParseIntent | SearchCatalog | GetProduct | Compare | GetReviews
    | SummarizeReviewEvidence | ProposePurchase | ConfirmAndPay | ReportNoMatch,
    Field(discriminator="type"),
]


class RecordedToolCall(ActionModel):
    sequence: int = Field(ge=0)
    action: Action
    arguments: dict[str, object]
    result_references: tuple[str, ...] = ()
    result_summary: str = Field(min_length=1)
    timestamp: dt.datetime


class EpisodeTermination(str):
    SUCCESS = "success"
    NO_MATCH = "no_match"
    INSTANT_KILL = "instant_kill"
    MALFORMED_ACTION = "malformed_action"
    TOOL_LIMIT = "tool_limit"
    MODEL_FAILURE = "model_failure"


class EpisodeRecord(ActionModel):
    schema_version: Literal["1.0"] = "1.0"
    episode_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    generation_id: str = Field(min_length=1)
    seed: int = Field(ge=0)
    tool_calls: tuple[RecordedToolCall, ...]
    final_answer: str = Field(min_length=1)
    recommended_products: tuple[str, ...] = ()
    refusal: ReportNoMatch | None = None
    payment_state: dict[str, object] = Field(default_factory=dict)
    score_components: dict[str, object] = Field(default_factory=dict)
    killed: bool = False
    kill_information: tuple[dict[str, object], ...] = ()
    termination: str
    token_count: int = Field(default=0, ge=0)
    cost: Decimal = Field(default=Decimal("0"), ge=0)
    started_at: dt.datetime
    ended_at: dt.datetime

    @model_validator(mode="after")
    def validate_sequence_and_times(self) -> EpisodeRecord:
        if [call.sequence for call in self.tool_calls] != list(range(len(self.tool_calls))):
            raise ValueError("episode tool calls must have contiguous ordered sequences")
        if self.ended_at < self.started_at:
            raise ValueError("ended_at cannot precede started_at")
        if self.killed != bool(self.kill_information):
            raise ValueError("killed must match kill_information")
        return self
