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
    """Record the buyer's request. `raw_message` is the buyer's message copied exactly, `category` the category exactly
    as the buyer wrote it, `max_total` the all-in budget as a number, and `assumptions` a non-empty list of short
    assumptions you make (for example ["budget includes tax and shipping"]). The budget is the dollar amount after
    "under"; other numbers in the message (such as "10k-ish") are not the budget."""
    type: Literal["parse_intent"] = "parse_intent"
    raw_message: str = Field(min_length=1)
    category: str = Field(min_length=1)
    max_total: Decimal = Field(gt=0, decimal_places=2)
    assumptions: tuple[str, ...] = Field(min_length=1)


class SearchCatalog(ActionModel):
    """Search the product catalog. `query` is words that appear in product titles (for example "water bottle"). If the buyer names only
    a category and a budget, pass an empty query "" to browse everything that passes the filters; never put the category name in `query`. `filters` accepts only `category` (the buyer's category, exactly as given) and `max_price` (a number, the
    buyer's budget); any other key is ignored. Example: {"query": "bike light", "filters": {"category": "Sports_and_Outdoors", "max_price": 25}}."""
    type: Literal["search_catalog"] = "search_catalog"
    query: str
    filters: dict[str, object] = Field(default_factory=dict)


class GetProduct(ActionModel):
    """Look up one product by id: title, price, in-stock variants and top features."""
    type: Literal["get_product"] = "get_product"
    product_id: str = Field(min_length=1)


class Compare(ActionModel):
    """Compare two or more candidate products side by side: titles, prices and in-stock variants. Always compare at least two products you have opened before buying; if only one product fits the budget, also include a product above the budget, for comparison only (never buy above the budget)."""
    type: Literal["compare"] = "compare"
    product_ids: tuple[str, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def unique_products(self) -> Compare:
        if len(self.product_ids) != len(set(self.product_ids)):
            raise ValueError("compare product_ids must be unique")
        return self


class GetReviews(ActionModel):
    """Read real customer reviews of one product. Call get_product on that product first. Each review has an `id` you must cite exactly in summarize_review_evidence. Read at least five (limit 5 to 10); a one-review query counts as gaming. Also call get_reviews with sort "critical" on a product you may buy, so your summary can cite a lower-rated review."""
    type: Literal["get_reviews"] = "get_reviews"
    product_id: str = Field(min_length=1)
    focus: str | None = Field(default=None, min_length=1)
    sort: ReviewSort = ReviewSort.RELEVANT
    limit: int = Field(default=10, ge=1, le=100)


class SummarizeReviewEvidence(ActionModel):
    """Record what the reviews you read say: one to three claims. Each claim needs: `concern`, one lowercase word naming the buyer concern it answers (for example durability, fit, value, quality; never null); `claim`, a specific sentence about that concern, not generic praise like "good product"; and `review_ids`, one to three DIFFERENT ids copied exactly from get_reviews for this product. Use different reviews for different concerns, and cite at least one lower-rated review when the ratings differ; citing only the top-rated reviews counts as gaming."""
    type: Literal["summarize_review_evidence"] = "summarize_review_evidence"
    product_id: str = Field(min_length=1)
    user_context: str = Field(min_length=1)
    claims: tuple[ReviewClaim, ...] = Field(min_length=1)


class ProposePurchase(ActionModel):
    """Propose buying one product. `variant` is a key of its variants_in_stock, or 'default' when none are listed; `expected_total` is the price you were shown and must not exceed the buyer's budget. Before proposing: open the product with get_product, compare at least two candidates, read its reviews, and summarize them."""
    type: Literal["propose_purchase"] = "propose_purchase"
    product_id: str = Field(min_length=1)
    variant: str = Field(min_length=1)
    expected_total: Decimal = Field(gt=0, decimal_places=2)
    assumptions: tuple[str, ...] = Field(min_length=1)


class ConfirmAndPay(ActionModel):
    """Pay for the pending order that propose_purchase returned. `pending_order_id` is that id exactly; set
    `user_confirmed` to true."""
    type: Literal["confirm_and_pay"] = "confirm_and_pay"
    pending_order_id: str = Field(min_length=1)
    user_confirmed: bool


class ReportNoMatch(ActionModel):
    """Report that nothing satisfies the buyer's category and budget. Use it ONLY when no product at or under the budget exists; if a search shows products within the budget, evaluate them instead of refusing. `closest_product_id` must be a real product id returned by a search: if your budget-filtered search found nothing, search again without max_price, open the two nearest products with get_product and compare them (reports without that research are penalized), then name the nearest one and say in why_it_misses how it misses. Never propose a purchase above the budget: if every product costs more, report no match."""
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
    result_content: dict[str, object] | None = None  # what the model is shown beyond ids: titles, prices, review text
    error_code: str | None = None
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
    model_metadata: tuple[dict[str, object], ...] = ()
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
