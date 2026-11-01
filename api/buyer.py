"""Buyer-facing agent/chat contract: API-owned, typed, provenance-carrying events with a polling-safe run status.

  POST /agent/runs                  start (idempotent on `request_id`); returns the run with its events so far
  GET  /agent/runs/{id}?after=SEQ   poll: only events with seq > SEQ, plus `next_seq`
  POST /agent/runs/{id}/confirm     the ONLY path to payment; needs `user_confirmed: true`

Rules enforced here: no reference answers or scorer labels exist in this path; every product and review carries its
source/as_of/snapshot provenance; unknown stock, size, shipping and tax are reported as unknown (never zero/true);
recommendations cite only review IDs verified complete and product-scoped; no payment without explicit confirmation;
budget is checked on the verified all-in total when the quote is all-in, and the event says which basis was used."""
from __future__ import annotations

import datetime as dt
import re
import threading
import uuid
from collections import OrderedDict
from decimal import Decimal
from typing import Annotated, Literal, Union

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from agents.actions import Compare, GetProduct, SummarizeReviewEvidence
from agents.buyer import BuyerAgent, BuyerOutcome
from catalog.providers.base import FrozenCatalogProvider, Product
from payments.errors import PaymentError
from payments.guards import GuardedPayments, GuardViolation

RUN_ID = re.compile(r"^[A-Za-z0-9_.-]{8,64}$")
MAX_RUNS = 500
EXCERPT = 240


# ---- events ---------------------------------------------------------------------------------------------------
class Provenance(BaseModel):
    source: str
    as_of: dt.datetime
    snapshot: bool
    catalog_manifest_hash: str | None = None
    source_id: str | None = None


class _Event(BaseModel):
    seq: int = 0
    at: dt.datetime | None = None


class IntentParsed(_Event):
    type: Literal["intent_parsed"] = "intent_parsed"
    category: str
    max_total: Decimal
    currency: str = "USD"
    budget_source: Literal["buyer", "model_parse"]  # model_parse => the UI should ask the buyer to confirm the cap


class Assumptions(_Event):
    type: Literal["assumptions"] = "assumptions"
    assumptions: list[str]
    unknown_constraints: list[str]  # facts the data cannot establish: stock, size, shipping, tax (when so)


class Research(_Event):
    type: Literal["research"] = "research"
    tool: str
    summary: str
    references: list[str] = []


class StockInfo(BaseModel):
    status: Literal["unknown", "in_stock", "out_of_stock"]
    units_by_variant: dict[str, int] = {}


class ProductCard(_Event):
    type: Literal["product_card"] = "product_card"
    product_id: str
    title: str
    brand: str | None
    category: str
    price: Decimal
    currency: str
    stock: StockInfo
    size_options: list[str] | None  # None = unknown
    recommended: bool
    provenance: Provenance


class ReviewCitation(_Event):
    type: Literal["review_citation"] = "review_citation"
    product_id: str
    review_id: str
    source_review_id: str | None
    concern: str
    claim: str
    excerpt: str | None
    rating: float | None
    date: dt.date | None
    provenance: Provenance


class Comparison(_Event):
    type: Literal["comparison"] = "comparison"
    product_ids: list[str]
    rows: dict[str, dict[str, str | None]]  # attribute -> product_id -> value (None = unknown)


class NoMatch(_Event):
    type: Literal["no_match"] = "no_match"
    reason: str
    why_it_misses: str
    closest_product_id: str | None
    closest_verified: bool
    assumptions: list[str]


class QuoteEvent(_Event):
    type: Literal["quote"] = "quote"
    quote_id: str
    product_id: str
    variant: str
    currency: str
    subtotal: Decimal
    shipping: Decimal | None
    tax: Decimal | None
    discounts: Decimal
    total: Decimal
    basis: Literal["all_in", "item_price_only"]
    unknown_components: list[str]
    quoted_at: dt.datetime
    expires_at: dt.datetime
    fresh: bool
    budget_cap: Decimal
    budget_checked_on: Literal["all_in_total", "item_price_total"]
    within_budget: bool


class ConfirmationRequest(_Event):
    type: Literal["confirmation_request"] = "confirmation_request"
    pending_order_id: str
    quote_id: str
    total: Decimal
    currency: str
    basis: Literal["all_in", "item_price_only"]
    summary: str
    requires_explicit_confirmation: bool = True


class PayPalApproval(_Event):
    type: Literal["paypal_approval"] = "paypal_approval"
    mode: Literal["sandbox", "mock"]
    status: str
    approval_url: str | None  # mock backends return a non-routable placeholder; sandbox returns the buyer's PayPal link


class Receipt(_Event):
    type: Literal["receipt"] = "receipt"
    mode: Literal["sandbox", "mock"]
    order_id: str
    capture_id: str
    amount: Decimal
    currency: str
    status: str


class ErrorEvent(_Event):
    type: Literal["error"] = "error"
    code: str
    message: str
    retryable: bool
    action: Literal["retry", "requote", "rephrase", "set_budget", "reconfigure_model", "none"]


Event = Annotated[Union[IntentParsed, Assumptions, Research, ProductCard, ReviewCitation, Comparison, NoMatch, QuoteEvent,
                        ConfirmationRequest, PayPalApproval, Receipt, ErrorEvent], Field(discriminator="type")]
RunStatus = Literal["running", "awaiting_confirmation", "completed", "failed"]


class BuyerRunRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    budget: Decimal | None = Field(default=None, gt=0, decimal_places=2)
    request_id: str | None = Field(default=None, description="client idempotency key; same id returns the same run")


class ConfirmBody(BaseModel):
    pending_order_id: str = Field(min_length=1)
    user_confirmed: bool


class BuyerRun(BaseModel):
    run_id: str
    status: RunStatus
    events: list[Event]
    next_seq: int
    model: str | None = None
    tokens: int = 0
    latency_ms: int = 0
    cost_usd: Decimal | None = None
    cost_known: bool = True


# ---- rendering ------------------------------------------------------------------------------------------------
def _provenance(p: Product) -> Provenance:
    return Provenance(source=p.source, as_of=p.as_of, snapshot=p.snapshot, catalog_manifest_hash=p.manifest_hash,
                      source_id=p.source_product_id)


def _stock(p: Product) -> StockInfo:
    if not p.variants:
        return StockInfo(status="unknown")  # the snapshot has no stock data: unknown, never "in stock"
    return StockInfo(status="in_stock" if any(u > 0 for u in p.variants.values()) else "out_of_stock",
                     units_by_variant=dict(p.variants))


def _excerpt(text: str) -> str:
    return " ".join(re.sub(r"<[^>]+>|&[a-z]+;", " ", text).split())[:EXCERPT]


def _mode(backend) -> Literal["sandbox", "mock"]:
    from payments.mock import MockPayments
    return "mock" if isinstance(backend, MockPayments) else "sandbox"


def render(outcome: BuyerOutcome, catalog: FrozenCatalogProvider, payments: GuardedPayments, backend, now: dt.datetime) -> list[_Event]:
    ev: list[_Event] = []
    if outcome.intent is not None:
        i = outcome.intent
        ev.append(IntentParsed(category=i.category, max_total=outcome.budget_cap or i.max_total, budget_source=outcome.budget_source))
    for r in outcome.records:
        a = r.action
        if a.type != "parse_intent":
            ev.append(Research(tool=a.type, summary=r.result_summary, references=list(r.result_references)))
    opened = list(dict.fromkeys(r.action.product_id for r in outcome.records if isinstance(r.action, GetProduct) and r.result_references))
    proposed = outcome.pending.product_id if outcome.pending else None
    products: dict[str, Product] = {}
    for pid in opened:
        p = catalog.get_product(pid)
        if p is not None:
            products[pid] = p
            ev.append(ProductCard(product_id=pid, title=p.title, brand=p.brand, category=p.category, price=p.price, currency=p.currency,
                                  stock=_stock(p), size_options=sorted(p.variants) or None, recommended=pid == proposed,
                                  provenance=_provenance(p)))
    for r in outcome.records:
        if isinstance(r.action, Compare):
            ids = [x for x in r.action.product_ids if x in products]
            ev.append(Comparison(product_ids=ids, rows={
                "price": {x: f"{products[x].price} {products[x].currency}" for x in ids},
                "brand": {x: products[x].brand for x in ids},
                "stock": {x: _stock(products[x]).status for x in ids},
                "source": {x: products[x].source for x in ids}}))
    cited: dict[str, dict] = {}
    for r in outcome.records:
        if isinstance(r.action, SummarizeReviewEvidence) and r.action.product_id in products:
            pid = r.action.product_id
            valid = catalog.get_review_ids(pid).ids  # complete + product-scoped, or the citation is dropped
            texts = cited.setdefault(pid, {x.id: x for x in catalog.get_reviews(pid, None, 100)})
            for c in r.action.claims:
                for rid in c.review_ids:
                    if rid in valid:
                        rv = texts.get(rid)
                        ev.append(ReviewCitation(product_id=pid, review_id=rid, source_review_id=rv.source_review_id if rv else None,
                                                 concern=c.concern, claim=c.claim, excerpt=_excerpt(rv.text) if rv else None,
                                                 rating=rv.rating if rv else None, date=rv.date if rv else None,
                                                 provenance=_provenance(products[pid])))
    if outcome.no_match is not None:
        n = outcome.no_match
        closest = catalog.get_product(n.closest_product_id) if n.closest_product_id else None
        ev.append(NoMatch(reason=n.reason, why_it_misses=n.why_it_misses, closest_product_id=closest.id if closest else None,
                          closest_verified=closest is not None, assumptions=list(n.assumptions)))
    unknown = []
    if outcome.pending is not None and outcome.pending.quote is not None:
        q, po = outcome.pending.quote, outcome.pending
        unknown = [name for name, v in (("shipping", q.shipping), ("tax", q.tax)) if v is None]
        ev.append(QuoteEvent(quote_id=q.quote_id, product_id=q.product_id, variant=q.variant, currency=q.currency, subtotal=q.subtotal,
                             shipping=q.shipping, tax=q.tax, discounts=q.discounts, total=q.total, basis=q.basis,
                             unknown_components=unknown, quoted_at=q.quoted_at, expires_at=q.expires_at, fresh=q.is_fresh(now),
                             budget_cap=outcome.budget_cap, budget_checked_on="all_in_total" if q.is_all_in else "item_price_total",
                             within_budget=q.total <= outcome.budget_cap))
        p = products.get(po.product_id)
        what = p.title if p else po.product_id
        tail = "" if q.is_all_in else f" Shipping and tax are unknown, so this is the item price only ({', '.join(unknown)} not included)."
        ev.append(ConfirmationRequest(pending_order_id=po.id, quote_id=q.quote_id, total=q.total, currency=q.currency, basis=q.basis,
                                      summary=f"Buy {what} for {q.total} {q.currency}?{tail} Nothing is charged until you confirm."))
        ev.append(PayPalApproval(mode=_mode(backend), status=backend.get_status(po.order_id),
                                 approval_url=backend.approval_url(po.order_id)))  # buyer's own approval link: never logged
    if outcome.intent is not None:
        stated = list(outcome.intent.assumptions)
        facts = [f for f in ("stock", "size") if not any(_stock(p).status != "unknown" for p in products.values())] + unknown
        ev.insert(1, Assumptions(assumptions=stated, unknown_constraints=facts))
    if outcome.kind == "failed":
        ev.append(error_event(outcome.error_code or "model_failed", outcome.retryable))
    return ev


ERRORS = {
    "model_unavailable": ("The model is not available right now.", "reconfigure_model"),
    "model_malformed_output": ("The model returned an unusable answer. Try again.", "retry"),
    "model_failed": ("The model failed. Try again.", "retry"),
    "timeout": ("The model took too long. Try again.", "retry"),
    "transport_error": ("The model service could not be reached. Try again.", "retry"),
    "budget_exceeded": ("The best match is over your budget once the total is verified. Raise the budget or rephrase.", "set_budget"),
    "budget_mismatch": ("Your budget and the request disagree. Set the budget explicitly.", "set_budget"),
    "price_mismatch": ("The price changed while the agent was working. Ask again.", "retry"),
    "out_of_stock": ("That item or variant is out of stock.", "rephrase"),
    "quote_stale": ("The quote expired. Request a new one before paying.", "requote"),
    "quote_changed": ("The price changed since the quote. Request a new quote.", "requote"),
    "quote_incomplete": ("Shipping and tax are unknown, so an all-in total cannot be verified.", "none"),
    "confirmation_required": ("Explicit confirmation is required before any payment.", "none"),
    "confirmation_not_allowed": ("Only you can confirm a purchase.", "none"),
    "invalid_action": ("The agent produced an invalid step. Try rephrasing.", "rephrase"),
    "step_limit": ("The agent could not finish in time. Try a more specific request.", "rephrase"),
    "payment_not_approved": ("Approve the payment in PayPal first, then confirm again.", "none"),
    "payment_failed": ("The payment provider rejected the payment.", "none"),
    "pending_order_not_found": ("There is nothing to confirm for this run.", "none"),
}


def error_event(code: str, retryable: bool = False) -> ErrorEvent:
    msg, action = ERRORS.get(code, ("Something went wrong.", "none"))
    return ErrorEvent(code=code, message=msg, retryable=retryable or action == "retry", action=action)


# ---- service ----------------------------------------------------------------------------------------------------
class ModelNotConfigured(Exception):
    """Typed `model_unavailable`: no buyer agent is configured for this deployment."""


class BuyerService:
    def __init__(self, agent: BuyerAgent | None, catalog: FrozenCatalogProvider, payments: GuardedPayments, backend,
                 clock=lambda: dt.datetime.now(dt.UTC)):
        self.agent, self.catalog, self.payments, self.backend, self.clock = agent, catalog, payments, backend, clock
        self._runs: OrderedDict[str, BuyerRun] = OrderedDict()
        self._lock = threading.Lock()

    @property
    def configured(self) -> bool:
        return self.agent is not None

    def _put(self, run: BuyerRun) -> None:
        with self._lock:
            self._runs[run.run_id] = run
            self._runs.move_to_end(run.run_id)
            while len(self._runs) > MAX_RUNS:
                self._runs.popitem(last=False)

    def _append(self, run_id: str, events: list[_Event], status: RunStatus | None = None) -> BuyerRun:
        with self._lock:
            run = self._runs[run_id]
            now = self.clock()
            for e in events:
                e.seq, e.at = run.next_seq, now
                run.events.append(e)
                run.next_seq += 1
            if status:
                run.status = status
            return run

    def start(self, req: BuyerRunRequest) -> BuyerRun:
        if self.agent is None:
            raise ModelNotConfigured()
        run_id = req.request_id or uuid.uuid4().hex
        if not RUN_ID.match(run_id):
            raise HTTPException(422, "invalid_request_id")
        with self._lock:
            if run_id in self._runs:  # idempotent: a retried POST never starts a second agent
                return self._runs[run_id]
            self._runs[run_id] = BuyerRun(run_id=run_id, status="running", events=[], next_seq=0)
        outcome = self.agent.run(run_id, req.message, req.budget)
        events = render(outcome, self.catalog, self.payments, self.backend, self.clock())
        status: RunStatus = {"proposal": "awaiting_confirmation", "no_match": "completed", "failed": "failed"}[outcome.kind]
        run = self._append(run_id, events, status)
        run.model = f"{outcome.model}@{(outcome.checkpoint or '')[:7]}" if outcome.model else None
        run.tokens, run.latency_ms, run.cost_known = outcome.tokens, outcome.latency_ms, outcome.cost is not None
        run.cost_usd = outcome.cost
        return run

    def get(self, run_id: str, after: int = -1) -> BuyerRun | None:
        with self._lock:
            run = self._runs.get(run_id)
            return None if run is None else run.model_copy(update={"events": [e for e in run.events if e.seq > after]})

    def confirm(self, run_id: str, body: ConfirmBody) -> BuyerRun:
        with self._lock:
            run = self._runs.get(run_id)
        if run is None:
            raise HTTPException(404, "run_not_found")
        offered = next((e for e in run.events if e.type == "confirmation_request"), None)
        if offered is None or offered.pending_order_id != body.pending_order_id:
            self._append(run_id, [error_event("pending_order_not_found")])
            raise HTTPException(404, "pending_order_not_found")
        if any(e.type == "receipt" for e in run.events):  # already captured: idempotent, no second capture attempt
            return self.get(run_id)
        try:
            cap = self.payments.confirm_and_pay(body.pending_order_id, body.user_confirmed)
        except PaymentError as exc:
            not_approved = exc.code == "ORDER_NOT_APPROVED"
            self._append(run_id, [error_event("payment_not_approved" if not_approved else "payment_failed")],
                         None if not_approved else "failed")
            raise
        except GuardViolation as exc:
            code = {"NotConfirmed": "confirmation_required"}.get(type(exc).__name__) or \
                   {"QuoteStale": "quote_stale", "QuoteChanged": "quote_changed", "QuoteIncomplete": "quote_incomplete",
                    "BudgetViolation": "budget_exceeded"}.get(type(exc).__name__, "guard_violation")
            self._append(run_id, [error_event(code)], None if code == "confirmation_required" else "failed")
            raise
        self._append(run_id, [Receipt(mode=_mode(self.backend), order_id=cap.order_id, capture_id=cap.capture_id, amount=cap.amount,
                                      currency=cap.currency, status=cap.status)], "completed")
        return self.get(run_id)


def buyer_router(service: BuyerService) -> APIRouter:
    r = APIRouter(tags=["agent"])

    @r.post("/agent/runs", response_model=BuyerRun)
    def start(req: BuyerRunRequest):
        return service.start(req)

    @r.get("/agent/runs/{run_id}", response_model=BuyerRun)
    def poll(run_id: str, after: Annotated[int, Query(ge=-1)] = -1):
        run = service.get(run_id, after)
        if run is None:
            raise HTTPException(404, "run_not_found")
        return run

    @r.post("/agent/runs/{run_id}/confirm", response_model=BuyerRun,
            description="The only path to payment. Requires user_confirmed=true; a stale or changed quote is refused with a typed error.")
    def confirm(run_id: str, body: ConfirmBody):
        return service.confirm(run_id, body)

    return r


class AgentRunFailed(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def to_agent_run_result(run: BuyerRun):
    """Legacy `/agent/run` shape built from the same events (one source of truth). Failed runs raise a typed error."""
    from api.world import AgentRunResult, PickOut, ReplayStep, ReviewEvidenceOut
    err = next((e for e in run.events if e.type == "error"), None)
    if err is not None and run.status == "failed":
        raise AgentRunFailed(err.code)
    by = lambda t: [e for e in run.events if e.type == t]
    intent, no_match = next(iter(by("intent_parsed")), None), next(iter(by("no_match")), None)
    cites = by("review_citation")
    picks = [PickOut(product_id=c.product_id, title=c.title, price=c.price, currency=c.currency, source=c.provenance.source,
                     as_of=c.provenance.as_of, snapshot=c.provenance.snapshot, reason="best verified match for the request",
                     review_evidence=[ReviewEvidenceOut(claim=r.claim, review_ids=[r.review_id], excerpt=r.excerpt, rating=r.rating,
                                                        date=r.date) for r in cites if r.product_id == c.product_id])
             for c in by("product_card") if c.recommended]
    quote = next(iter(by("quote")), None)
    answer = (f"No realistic match: {no_match.reason}" if no_match else
              f"Recommend {picks[0].title}. Total {quote.total} {quote.currency} ({quote.basis}); awaiting your confirmation."
              if picks and quote else "Run completed.")
    return AgentRunResult(
        parsed_intent=intent.model_dump(mode="json") if intent else {}, assumptions=(next(iter(by("assumptions")), None) and by("assumptions")[0].assumptions) or [],
        steps=[ReplayStep(sequence=e.seq, tool=e.tool, arguments={}, result_references=e.references, result_summary=e.summary,
                          error_code=None, timestamp=e.at) for e in by("research")],
        picks=picks, no_match=no_match is not None, closest_product_id=no_match.closest_product_id if no_match else None,
        final_answer=answer, model=run.model or "unknown", latency_ms=run.latency_ms, cost_usd=run.cost_usd,
        run_id=run.run_id, status=run.status)
