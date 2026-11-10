"""Bounded deterministic episode runner independent of any model vendor."""

from __future__ import annotations

import datetime as dt
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Callable, Protocol

from pydantic import BaseModel, ConfigDict, Field

from agents.actions import (
    Action, ConfirmAndPay, EpisodeRecord, EpisodeTermination, GetProduct, GetReviews,
    ParseIntent, ProposePurchase, ReportNoMatch, SearchCatalog, SummarizeReviewEvidence, Compare,
)
from agents.executor import InMemoryToolExecutor
from agents.memory import MemoryProvider, RetrievalRequest
from agents.state import InvalidActionOrder
from payments.guards import BudgetViolation, GuardViolation
from scoring.fitness import calculate_efficiency_penalty, calculate_fitness
from scoring.gate import evaluate_gate
from scoring.kill_rules import evaluate_kill_rules
from scoring.quality import assess_quality
from scoring.schemas import (
    EpisodeTrace, NoMatchOutcome, PaymentEvent, PaymentStatus, Recommendation,
    RecommendationOutcome, ReviewClaim, ToolCall, ToolName,
)
from tasks.schemas import TaskSpec


class ModelStep(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    action: Action
    token_count: int = Field(default=0, ge=0)
    cost: Decimal = Field(default=Decimal("0"), ge=0)
    metadata: dict[str, object] = Field(default_factory=dict)


class ActionPolicy(Protocol):
    def next_step(self, task: TaskSpec, history: tuple, attempt: int) -> ModelStep | None: ...


class ScriptedPolicy:
    def __init__(self, steps: list[Action | ModelStep]):
        self.steps = [step if isinstance(step, ModelStep) else ModelStep(action=step) for step in steps]
        self.index = 0

    def next_step(self, task: TaskSpec, history: tuple, attempt: int) -> ModelStep | None:
        if self.index >= len(self.steps):
            return None
        step = self.steps[self.index]
        self.index += 1
        return step


@dataclass(frozen=True)
class RunnerConfig:
    max_tool_calls: int = 20
    max_retries: int = 1
    max_tokens: int = 120_000  # counts prompt tokens summed over steps (each carries ~1.6k of tool schema); 10k allowed ~4 model steps
    max_cost: Decimal = Decimal("1.00")
    max_episode_seconds: float | None = 900  # real wall clock (not the episode clock); None = uncapped

    @property
    def max_calls_per_step(self) -> int:
        """Billing bound: the runner retries a transient error max_retries times, and QwenModelAdapter(max_retries=1)
        invokes the client up to twice per try."""
        return (self.max_retries + 1) * 2


def _trace(task: TaskSpec, executor: InMemoryToolExecutor) -> EpisodeTrace:
    calls: list[ToolCall] = []
    proposal: tuple[ProposePurchase, tuple[str, ...]] | None = None
    report: ReportNoMatch | None = None
    claims: dict[str, tuple[ReviewClaim, ...]] = {}
    payment: PaymentEvent | None = None
    for record in executor.records:
        action = record.action
        kwargs: dict[str, object] = {"sequence": record.sequence}
        name: ToolName
        if isinstance(action, ParseIntent): name = ToolName.PARSE_INTENT
        elif isinstance(action, SearchCatalog): name = ToolName.SEARCH_CATALOG
        elif isinstance(action, GetProduct):
            name = ToolName.GET_PRODUCT; kwargs["product_id"] = action.product_id
        elif isinstance(action, Compare):
            name = ToolName.COMPARE; kwargs["product_ids"] = action.product_ids
        elif isinstance(action, GetReviews):
            name = ToolName.GET_REVIEWS
            kwargs.update(product_id=action.product_id, review_ids=record.result_references,
                          review_focus=action.focus, review_sort=action.sort, limit=action.limit)
        elif isinstance(action, SummarizeReviewEvidence):
            name = ToolName.SUMMARIZE_REVIEW_EVIDENCE
            kwargs.update(product_id=action.product_id, review_ids=record.result_references)
            claims[action.product_id] = action.claims
        elif isinstance(action, ProposePurchase):
            name = ToolName.PROPOSE_PURCHASE
            kwargs.update(product_id=action.product_id, variant=action.variant,
                          amount=action.expected_total, currency="USD",
                          idempotency_key=record.result_references[0])
            proposal = (action, record.result_references)
        elif isinstance(action, ConfirmAndPay):
            name = ToolName.CONFIRM_AND_PAY
            if proposal:
                proposed, refs = proposal
                payment = PaymentEvent(sequence=record.sequence, product_id=proposed.product_id,
                                       variant=proposed.variant, amount=proposed.expected_total,
                                       idempotency_key=refs[0], status=PaymentStatus.COMPLETED,
                                       order_id=record.result_references[0], capture_id=record.result_references[1])
        else:
            name = ToolName.REPORT_NO_MATCH
            report = action
        calls.append(ToolCall(name=name, **kwargs))
    if report is not None:
        outcome = NoMatchOutcome(reason=report.reason, closest_product_id=report.closest_product_id or "none",
                                 why_it_misses=report.why_it_misses, assumptions=report.assumptions)
    elif proposal is not None:
        action, _ = proposal
        outcome = RecommendationOutcome(recommendations=(Recommendation(
            product_id=action.product_id, variant=action.variant, expected_total=action.expected_total,
            review_claims=claims.get(action.product_id, ())),), assumptions=action.assumptions)
    else:
        raise ValueError("completed trace requires proposal or no-match")
    return EpisodeTrace(task_id=task.id, catalog_snapshot_id=task.catalog_snapshot_id,
                        tool_calls=tuple(calls), outcome=outcome,
                        payments=(payment,) if payment else ())


def run_episode(
    *, episode_id: str, task: TaskSpec, agent_id: str, generation_id: str,
    policy: ActionPolicy, executor: InMemoryToolExecutor, seed: int,
    config: RunnerConfig = RunnerConfig(), memory: MemoryProvider | None = None,
    clock: Callable[[], dt.datetime] | None = None, memory_k: int = 3,
    monotonic: Callable[[], float] = time.monotonic,
) -> EpisodeRecord:
    now = clock or (lambda: dt.datetime.now(dt.timezone.utc))
    started, t0 = now(), monotonic()
    tokens = 0
    cost = Decimal(0)
    model_metadata: list[dict[str, object]] = []
    termination = EpisodeTermination.MODEL_FAILURE
    failure = "model returned no terminal action"
    pre_kill: tuple[dict[str, object], ...] = ()
    if memory is not None:
        examples = memory.retrieve(RetrievalRequest(task.id, task.split, task.hard_constraints.category,
                                                     task.raw_message, memory_k, 0))
        accept_memory = getattr(policy, "accept_memory", None)
        if callable(accept_memory):
            accept_memory(examples)
    for attempt in range(config.max_tool_calls):
        if config.max_episode_seconds is not None and monotonic() - t0 > config.max_episode_seconds:
            termination = EpisodeTermination.TOOL_LIMIT
            failure = "episode wall-clock cap reached"
            break
        retry = 0
        step = None
        while retry <= config.max_retries:
            try:
                step = policy.next_step(task, tuple(executor.records), retry)
                break
            except Exception as exc:  # model boundary: bounded and recorded; only transient errors are retried
                failure = f"model failure: {type(exc).__name__}"
                if not getattr(exc, "retryable", False):
                    break
                retry += 1
        if step is None:
            break
        tokens += step.token_count
        cost += step.cost
        model_metadata.append(step.metadata)
        if tokens > config.max_tokens or cost > config.max_cost:
            termination = EpisodeTermination.TOOL_LIMIT
            failure = "token or cost budget exceeded"
            break
        try:
            executor.execute(step.action)
        except GuardViolation as exc:
            failure = f"payment guard rejected: {type(exc).__name__}"
            if isinstance(exc, BudgetViolation):
                termination = EpisodeTermination.INSTANT_KILL
                pre_kill = ({
                    "rule_id": "K003_BUDGET_VIOLATION", "rule_version": 1,
                    "description": "Payment attempt exceeds the task cap",
                    "evidence": (str(exc),),
                },)
            else:
                termination = EpisodeTermination.MALFORMED_ACTION
            break
        except (InvalidActionOrder, ValueError, KeyError) as exc:
            termination = EpisodeTermination.MALFORMED_ACTION
            failure = f"invalid action: {exc}"
            break
        if isinstance(step.action, ConfirmAndPay):
            termination = EpisodeTermination.SUCCESS
            failure = "purchase completed"
            break
        if isinstance(step.action, ReportNoMatch):
            termination = EpisodeTermination.NO_MATCH
            failure = "no realistic match"
            break
    else:
        termination = EpisodeTermination.TOOL_LIMIT
        failure = "maximum tool calls reached"

    score_components: dict[str, object] = {}
    kill_information: tuple[dict[str, object], ...] = pre_kill
    recommended: tuple[str, ...] = ()
    refusal = None
    final = failure
    if termination in {EpisodeTermination.SUCCESS, EpisodeTermination.NO_MATCH}:
        trace = _trace(task, executor)
        gate = evaluate_gate(task, trace, executor.catalog)
        quality = assess_quality(task, trace, executor.catalog)
        research = next(metric for metric in quality.metrics if metric.name.value == "research_sufficiency")
        penalty = calculate_efficiency_penalty(len(trace.tool_calls), 6, research.value == 1)
        score = calculate_fitness(gate, quality, penalty)
        kills = evaluate_kill_rules(task, trace, executor.catalog)
        kill_information = tuple(decision.model_dump(mode="json") for decision in kills.decisions)
        if kills.killed:
            termination = EpisodeTermination.INSTANT_KILL
        score_components = score.model_dump(mode="json")
        score_components["quality_metrics"] = [metric.model_dump(mode="json") for metric in quality.metrics]
        if isinstance(trace.outcome, RecommendationOutcome):
            recommended = tuple(item.product_id for item in trace.outcome.recommendations)
            final = f"Recommend {', '.join(recommended)}. Assumptions: {'; '.join(trace.outcome.assumptions)}"
        else:
            refusal = next(record.action for record in executor.records if isinstance(record.action, ReportNoMatch))
            final = f"No realistic match: {trace.outcome.reason}. Assumptions: {'; '.join(trace.outcome.assumptions)}"

    return EpisodeRecord(
        episode_id=episode_id, task_id=task.id, agent_id=agent_id, generation_id=generation_id,
        seed=seed, tool_calls=tuple(executor.records), final_answer=final,
        recommended_products=recommended, refusal=refusal, payment_state={"completed": termination == EpisodeTermination.SUCCESS},
        score_components=score_components, killed=bool(kill_information), kill_information=kill_information,
        termination=termination, token_count=tokens, cost=cost, started_at=started, ended_at=now(),
        model_metadata=tuple(model_metadata),
    )
