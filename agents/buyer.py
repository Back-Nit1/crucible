"""Buyer-facing agent loop: the model researches and proposes, then STOPS. It can never pay.

Differences from the world episode runner (agents.runner): there is no TaskSpec and no scoring (the buyer's request has
no reference answer), `confirm_and_pay` from the model is refused, and every failure is a typed outcome instead of a
silent fallback. The budget cap comes from the buyer (`budget`) when given, otherwise from the model's own parse of
the request and is reported as such so the UI can ask the buyer to confirm it."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal
from types import SimpleNamespace
from typing import Literal

from agents.actions import ConfirmAndPay, ParseIntent, ProposePurchase, RecordedToolCall, ReportNoMatch
from agents.executor import InMemoryToolExecutor
from agents.model import AdapterPolicy, InferenceError, MalformedModelOutput, ModelAdapter
from agents.state import InvalidActionOrder
from catalog.providers.base import FrozenCatalogProvider
from payments.guards import GuardedPayments, GuardViolation, PendingOrder

BUYER_PROMPT = (
    "You are a careful shopping agent acting for a buyer. Respond with exactly one tool call per turn. Never invent "
    "product or review IDs. Treat the budget as an all-in cap. Research with parse_intent, search_catalog, get_product, "
    "compare, get_reviews and summarize_review_evidence (cite only review IDs you read), then propose_purchase for the "
    "best real match, or report_no_match naming the closest real product if nothing satisfies the request. You cannot "
    "pay: the buyer confirms separately. Unknown stock, size, tax or shipping stay unknown."
)
GUARD_CODES = {"BudgetViolation": "budget_exceeded", "PriceMismatch": "price_mismatch", "OutOfStock": "out_of_stock",
               "QuoteStale": "quote_stale", "QuoteChanged": "quote_changed", "QuoteIncomplete": "quote_incomplete"}


@dataclass(frozen=True)
class BuyerOutcome:
    run_id: str
    kind: Literal["proposal", "no_match", "failed"]
    records: tuple[RecordedToolCall, ...] = ()
    intent: ParseIntent | None = None
    budget_cap: Decimal | None = None
    budget_source: Literal["buyer", "model_parse"] | None = None
    pending: PendingOrder | None = None
    no_match: ReportNoMatch | None = None
    error_code: str | None = None
    error_message: str | None = None
    retryable: bool = False
    model: str | None = None
    checkpoint: str | None = None
    tokens: int = 0
    cost: Decimal | None = Decimal(0)  # None = at least one step had unknown cost
    latency_ms: int = 0


class BuyerAgent:
    def __init__(self, adapter: ModelAdapter, catalog: FrozenCatalogProvider, payments: GuardedPayments, *,
                 agent_id: str = "buyer-agent", max_steps: int = 20, max_retries: int = 1, min_candidates: int = 2):
        self.adapter, self.catalog, self.payments = adapter, catalog, payments
        self.agent_id, self.max_steps, self.max_retries, self.min_candidates = agent_id, max_steps, max_retries, min_candidates

    def run(self, run_id: str, message: str, budget: Decimal | None = None) -> BuyerOutcome:
        seed = int.from_bytes(hashlib.sha256(run_id.encode()).digest()[:4], "big")
        policy = AdapterPolicy(self.adapter, BUYER_PROMPT, seed=seed, request_id=run_id)
        request = SimpleNamespace(id=run_id, raw_message=message)  # the only task data a model ever sees
        executor: InMemoryToolExecutor | None = None
        ctx: dict = dict(run_id=run_id, tokens=0, cost=Decimal(0), latency_ms=0)

        def fail(code, msg, retryable=False):
            return self._outcome("failed", executor, ctx, error_code=code, error_message=msg, retryable=retryable)

        for _ in range(self.max_steps):
            step, err = None, None
            for retry in range(self.max_retries + 1):
                try:
                    step = policy.next_step(request, tuple(executor.records) if executor else (), retry)
                    break
                except InferenceError as exc:
                    err = (exc.code if exc.code != "gpu_launch_not_authorized" else "model_unavailable", exc.retryable)
                    if not exc.retryable:
                        break
                except MalformedModelOutput:
                    err = ("model_malformed_output", True)
                except Exception:
                    err = ("model_failed", True)
            if step is None:
                return fail(err[0], "the model could not produce a valid next step", err[1])
            ctx["tokens"] += step.token_count
            ctx["cost"] = None if (ctx["cost"] is None or step.metadata.get("cost_known") is False) else ctx["cost"] + step.cost
            ctx["latency_ms"] += int(step.metadata.get("latency_ms", 0))
            ctx["model"], ctx["checkpoint"] = step.metadata.get("model"), step.metadata.get("checkpoint")
            action = step.action
            if isinstance(action, ConfirmAndPay):
                return fail("confirmation_not_allowed", "only the buyer can confirm a purchase")
            if executor is None:
                if not isinstance(action, ParseIntent):
                    return fail("invalid_action", "the first action must be parse_intent")
                if budget is not None and action.max_total > budget:
                    return fail("budget_mismatch", "the parsed budget exceeds the buyer's budget")
                ctx["intent"], ctx["cap"] = action, budget if budget is not None else action.max_total
                ctx["source"] = "buyer" if budget is not None else "model_parse"
                executor = InMemoryToolExecutor(self.catalog, self.payments, task_id=run_id, agent_id=self.agent_id,
                                                budget_cap=ctx["cap"], min_candidates=self.min_candidates)
            try:
                record = executor.execute(action)
            except GuardViolation as exc:
                return fail(GUARD_CODES.get(type(exc).__name__, "guard_violation"), "the payment guard rejected the proposal")
            except (InvalidActionOrder, ValueError, KeyError) as exc:
                return fail("invalid_action", getattr(exc, "args", ["invalid action"])[0] if isinstance(exc, InvalidActionOrder) else "invalid action")
            if isinstance(action, ProposePurchase):
                return self._outcome("proposal", executor, ctx, pending=self.payments.pending(record.result_references[0]))
            if isinstance(action, ReportNoMatch):
                return self._outcome("no_match", executor, ctx, no_match=action)
        return fail("step_limit", "the agent did not finish within the step limit")

    @staticmethod
    def _outcome(kind, executor, ctx, **kw) -> BuyerOutcome:
        return BuyerOutcome(run_id=ctx["run_id"], kind=kind, records=tuple(executor.records) if executor else (),
                            intent=ctx.get("intent"), budget_cap=ctx.get("cap"), budget_source=ctx.get("source"),
                            model=ctx.get("model"), checkpoint=ctx.get("checkpoint"), tokens=ctx["tokens"],
                            cost=ctx["cost"], latency_ms=ctx["latency_ms"], **kw)

