"""Typed FastAPI service (spec 7.1). Thin layer over ProviderRouter + GuardedPayments.
Errors are structured `{"error": {"code", "message"}}`; internals, tokens and upstream bodies never leak."""
import logging
import os
from decimal import Decimal
from typing import Annotated

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from catalog.router import ProductResult, ProviderRouter, ProviderUnavailable, ReviewsResult, SearchResult
from payments.errors import PaymentError
from payments.guards import (BudgetViolation, GuardedPayments, GuardViolation, NotConfirmed, OutOfStock,
                             PriceMismatch, QuoteChanged, QuoteIncomplete, QuoteStale)
from payments.mock import MockPayments

log = logging.getLogger("crucible.api")


class ProposeRequest(BaseModel):
    task_id: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    product_id: str = Field(min_length=1)
    variant: str = ""
    expected_total: Decimal = Field(gt=0, decimal_places=2)
    budget_cap: Decimal = Field(gt=0, decimal_places=2)


class ProposeResponse(BaseModel):
    pending_order_id: str
    product_id: str
    total: Decimal
    currency: str
    status: str
    approval_url: str | None = None  # sandbox buyer approval link; None for the mock
    quote_id: str | None = None
    quote_basis: str = "item_price_only"  # "all_in" only when shipping and tax are known; never implied otherwise


class ConfirmRequest(BaseModel):
    pending_order_id: str = Field(min_length=1)
    user_confirmed: bool  # must be explicitly true; capture never happens otherwise


class ConfirmResponse(BaseModel):
    order_id: str
    capture_id: str
    amount: Decimal
    currency: str
    status: str


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody


class ProviderStatus(BaseModel):
    live_chat: str
    training_eval: str
    providers: dict


class _RouterCatalog:
    """Adapts the router to the CatalogProvider shape the payment guards use (live price re-check)."""

    def __init__(self, router: ProviderRouter):
        self.router = router

    def get_product(self, product_id):
        return self.router.get_product(product_id).product


def _err(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def default_router() -> ProviderRouter:
    """Real providers from env; anything unconfigured is simply absent (router reports it)."""
    from catalog.providers.elastic import Elastic, ElasticCatalogProvider, endpoint_from_cloud_id
    provs = {}
    if os.environ.get("ELASTIC_API_KEY") and (os.environ.get("ELASTIC_ENDPOINT") or os.environ.get("ELASTIC_CLOUD_ID")):
        url = os.environ.get("ELASTIC_ENDPOINT") or endpoint_from_cloud_id(os.environ["ELASTIC_CLOUD_ID"])
        provs["elastic_snapshot"] = ElasticCatalogProvider(Elastic(url))
    if os.environ.get("CHANNEL3_API_KEY"):
        from catalog.providers.channel3 import Channel3Provider
        provs["channel3"] = Channel3Provider()
    return ProviderRouter(provs)


def default_backend():
    if os.environ.get("PAYMENTS_BACKEND") == "sandbox":
        from payments.sandbox import SandboxPayments
        return SandboxPayments()
    return MockPayments(auto_approve=False)


def create_app(router: ProviderRouter | None = None, backend=None) -> FastAPI:
    app = FastAPI(title="Crucible Agent API", version="0.1.0")
    state: dict = {}

    def get_router() -> ProviderRouter:
        state.setdefault("router", router or default_router())
        return state["router"]

    def get_payments() -> GuardedPayments:
        if "payments" not in state:
            state["backend"] = backend or default_backend()
            state["payments"] = GuardedPayments(state["backend"], _RouterCatalog(get_router()),
                                                require_all_in=os.environ.get("REQUIRE_ALL_IN_QUOTE") == "1")
        return state["payments"]

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, e: RequestValidationError):
        return _err(422, "invalid_request", "; ".join(f"{'.'.join(map(str, x['loc'][1:]))}: {x['msg']}" for x in e.errors()))

    @app.exception_handler(ProviderUnavailable)
    async def _unavailable(_: Request, e: ProviderUnavailable):
        return _err(503, "provider_unavailable", f"catalog provider '{e}' is not configured")

    @app.exception_handler(GuardViolation)
    async def _guard(_: Request, e: GuardViolation):
        code = {BudgetViolation: "budget_exceeded", PriceMismatch: "price_mismatch", OutOfStock: "out_of_stock",
                NotConfirmed: "confirmation_required", QuoteStale: "quote_stale", QuoteChanged: "quote_changed",
                QuoteIncomplete: "quote_incomplete"}.get(type(e), "guard_violation")
        return _err(409 if code != "confirmation_required" else 428, code, str(e))

    @app.exception_handler(PaymentError)
    async def _payment(_: Request, e: PaymentError):
        return _err(402, "payment_failed", e.code)  # PayPal issue code only; no body, no debug ids

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, e: Exception):
        log.exception("unhandled error")  # detail goes to logs only
        return _err(500, "internal_error", "internal error")

    errs = {422: {"model": ErrorResponse}, 500: {"model": ErrorResponse}}

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/providers/status", response_model=ProviderStatus)
    def providers_status():
        return get_router().status()

    @app.get("/catalog/search", response_model=SearchResult, responses=errs)
    def search(q: Annotated[str, Query(min_length=1)], category: str | None = None,
               max_price: Decimal | None = None, min_price: Decimal | None = None):
        filters = {k: v for k, v in dict(category=category, max_price=max_price, min_price=min_price).items() if v is not None}
        return get_router().search(q, filters)

    @app.get("/catalog/products/{product_id}", response_model=ProductResult, responses={404: {"model": ErrorResponse}, **errs})
    def product(product_id: str):
        r = get_router().get_product(product_id)
        return r if r.product else _err(404, "product_not_found", product_id)

    @app.get("/catalog/products/{product_id}/reviews", response_model=ReviewsResult, responses=errs)
    def reviews(product_id: str, focus: str | None = None, limit: Annotated[int, Query(ge=1, le=50)] = 10):
        return get_router().get_reviews(product_id, focus, limit)

    @app.post("/purchase/propose", response_model=ProposeResponse, responses={409: {"model": ErrorResponse}, **errs})
    def propose(req: ProposeRequest):
        g = get_payments()
        p = g.propose_purchase(req.task_id, req.agent_id, req.product_id, req.variant, req.expected_total, req.budget_cap)
        b = state["backend"]
        return ProposeResponse(pending_order_id=p.id, product_id=p.product_id, total=p.total, currency=p.currency,
                               quote_id=p.quote_id, quote_basis=p.quote_basis,
                               status=b.get_status(p.order_id), approval_url=b.approval_url(p.order_id) if hasattr(b, "approval_url") else None)

    @app.post("/purchase/confirm", response_model=ConfirmResponse, responses={428: {"model": ErrorResponse}, **errs})
    def confirm(req: ConfirmRequest):
        g = get_payments()
        if req.pending_order_id not in g._pending:
            return _err(404, "pending_order_not_found", req.pending_order_id)
        return g.confirm_and_pay(req.pending_order_id, req.user_confirmed)

    return app


app = create_app()
