"""Typed FastAPI service (spec 7.1). Thin layer over ProviderRouter + GuardedPayments.
Errors are structured `{"error": {"code", "message"}}`; internals, tokens and upstream bodies never leak."""
import json
import logging
import os
import time
import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from catalog.router import ProductResult, ProviderRouter, ProviderUnavailable, ReviewsResult, SearchResult
from api.buyer import AgentRunFailed, BuyerService, ModelNotConfigured, buyer_router, to_agent_run_result
from api.world import ModelUnavailable, WorldDataUnavailable, world_router
from payments.errors import PaymentError, PaymentUnavailable
from payments.ledger import PaymentLedger
from payments.sandbox import SandboxPayments
from payments.guards import (BudgetViolation, GuardedPayments, GuardViolation, NotConfirmed, OutOfStock,
                             PriceMismatch, QuoteChanged, QuoteIncomplete, QuoteStale)
from payments.mock import MockPayments

log = logging.getLogger("crucible.api")
APP_VERSION = "0.2.0"


def configure_logging() -> None:
    """One JSON object per line on stdout (Render/Modal collect it). Idempotent."""
    if not any(getattr(h, "_crucible", False) for h in logging.getLogger().handlers):
        h = logging.StreamHandler()
        h._crucible = True
        h.setFormatter(logging.Formatter("%(message)s"))
        logging.getLogger("crucible").addHandler(h)
        logging.getLogger("crucible").setLevel(logging.INFO)
        logging.getLogger("crucible").propagate = False


def demo_mode() -> bool:
    return os.environ.get("DEMO_MODE") == "1"


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


def default_reader():
    from api.readers import ElasticReader
    from catalog.providers.elastic import Elastic, endpoint_from_cloud_id
    if not (os.environ.get("ELASTIC_API_KEY") and (os.environ.get("ELASTIC_ENDPOINT") or os.environ.get("ELASTIC_CLOUD_ID"))):
        raise WorldDataUnavailable()
    url = os.environ.get("ELASTIC_ENDPOINT") or endpoint_from_cloud_id(os.environ["ELASTIC_CLOUD_ID"])
    return ElasticReader(Elastic(url))


def default_buyer(router: ProviderRouter, backend, ledger=None) -> BuyerService:
    """Buyer service over the frozen Elastic snapshot. The model is attached only if Modal launch is authorized;
    otherwise the service answers every run with the typed `model_unavailable` error (no silent fallback)."""
    from agents.buyer import BuyerAgent
    from agents.model import InferenceError, QwenModelAdapter
    from agents.qwen_client import ModalQwenClient
    catalog = router.providers.get("elastic_snapshot")
    if catalog is None:
        raise ProviderUnavailable("elastic_snapshot")
    payments = GuardedPayments(backend, catalog, require_all_in=os.environ.get("REQUIRE_ALL_IN_QUOTE") == "1", ledger=ledger)
    try:
        agent = BuyerAgent(QwenModelAdapter(ModalQwenClient.from_environment(), max_retries=1), catalog, payments)
    except InferenceError:
        agent = None
    return BuyerService(agent, catalog, payments, backend)


class _BuyerBackedRunner:
    """`/agent/run` over the buyer service (used when no runner is injected)."""

    def __init__(self, get_buyer):
        self.get_buyer = get_buyer

    def run(self, request):
        from api.buyer import BuyerRunRequest
        return to_agent_run_result(self.get_buyer().start(BuyerRunRequest(message=request.message)))


def create_app(router: ProviderRouter | None = None, backend=None, reader=None, runner=None, buyer: BuyerService | None = None) -> FastAPI:
    app = FastAPI(title="Crucible Agent API", version="0.1.0")
    state: dict = {}

    def get_router() -> ProviderRouter:
        state.setdefault("router", router or default_router())
        return state["router"]

    def get_payments() -> GuardedPayments:
        if "payments" not in state:
            state["backend"] = backend or default_backend()
            state["ledger"] = PaymentLedger("sandbox") if isinstance(state["backend"], SandboxPayments) else None
            state["payments"] = GuardedPayments(state["backend"], _RouterCatalog(get_router()),
                                                require_all_in=os.environ.get("REQUIRE_ALL_IN_QUOTE") == "1",
                                                ledger=state["ledger"])
        return state["payments"]

    def get_buyer() -> BuyerService:
        if "buyer" not in state:
            get_payments()  # fixes the shared backend
            state["buyer"] = buyer or (default_buyer(get_router(), state["backend"], state["ledger"]) if _launch_authorized()
                                       else BuyerService(None, None, None, None))  # typed model_unavailable, no provider touched
        return state["buyer"]

    origins = [o.strip().rstrip("/") for o in os.environ.get("CORS_ALLOW_ORIGINS", "").split(",") if o.strip()]
    if origins:  # default none: same-origin only. No credentials/cookies are used, so no allow_credentials.
        from fastapi.middleware.cors import CORSMiddleware
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST"],
                           allow_headers=["content-type", "x-request-id"], expose_headers=["x-request-id"])

    @app.middleware("http")
    async def _access_log(request: Request, call_next):
        """Structured access log: path only (never query string / body, which can hold shopper text), latency, status.
        `cost_usd` is added by handlers that spend money (agent runs) via request.state."""
        rid, t0 = request.headers.get("x-request-id") or uuid.uuid4().hex[:16], time.perf_counter()
        request.state.cost_usd = None
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["x-request-id"] = rid
            return response
        finally:
            log.info(json.dumps({"event": "request", "request_id": rid, "method": request.method, "path": request.url.path,
                                 "status": status, "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
                                 "cost_usd": request.state.cost_usd}))

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

    @app.exception_handler(PaymentUnavailable)
    async def _payment_unavailable(_: Request, e: PaymentUnavailable):
        return _err(503, "payment_unavailable", "PayPal is temporarily unavailable; retry the same request")

    @app.exception_handler(PaymentError)
    async def _payment(_: Request, e: PaymentError):
        return _err(402, "payment_failed", e.code)  # PayPal issue code only; no body, no debug ids

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, e: Exception):
        log.exception("unhandled error")  # detail goes to logs only
        return _err(500, "internal_error", "internal error")

    @app.exception_handler(ModelNotConfigured)
    async def _no_buyer_model(_: Request, e: ModelNotConfigured):
        return _err(503, "model_unavailable", "no model endpoint is configured")

    @app.exception_handler(AgentRunFailed)
    async def _run_failed(_: Request, e: AgentRunFailed):
        from api.buyer import ERRORS
        status = 503 if e.code in {"model_unavailable", "timeout", "transport_error"} else 502
        return _err(status, e.code, ERRORS.get(e.code, ("The agent run failed.",))[0])

    @app.exception_handler(ModelUnavailable)
    async def _no_model(_: Request, e: ModelUnavailable):
        return _err(503, "model_unavailable", "no model endpoint is configured")

    @app.exception_handler(WorldDataUnavailable)
    async def _no_world(_: Request, e: WorldDataUnavailable):
        return _err(503, "world_data_unavailable", "the trace store is not configured")

    @app.exception_handler(HTTPException)
    async def _http(_: Request, e: HTTPException):
        return _err(e.status_code, str(e.detail), str(e.detail).replace("_", " "))

    errs = {422: {"model": ErrorResponse}, 500: {"model": ErrorResponse}}

    @app.get("/health")
    def health():
        """Liveness only: no dependencies touched, safe for Render's health check and keep-alive pings."""
        return {"status": "ok"}

    @app.get("/ready")
    def ready():
        """Readiness: which backends are configured (names and booleans only, never values)."""
        env = os.environ
        return {"status": "ok", "version": APP_VERSION, "checks": {
            "elastic_configured": bool(env.get("ELASTIC_API_KEY") and (env.get("ELASTIC_ENDPOINT") or env.get("ELASTIC_CLOUD_ID"))),
            "paypal_sandbox_configured": bool(env.get("PAYPAL_CLIENT_ID") and env.get("PAYPAL_CLIENT_SECRET")),
            "model_configured": runner is not None or (buyer is not None and buyer.configured) or _launch_authorized(),
            "demo_mode": demo_mode()}}

    @app.get("/config")
    def public_config():
        """Non-secret deployment settings the web app needs (labels the data honestly)."""
        return {"version": APP_VERSION, "demo_mode": demo_mode(),
                "payments": "sandbox" if os.environ.get("PAYMENTS_BACKEND") == "sandbox" else "mock",
                "require_all_in_quote": os.environ.get("REQUIRE_ALL_IN_QUOTE") == "1",
                "catalog": get_router().status()["live_chat"], "snapshot_as_of": "2023-09-30",
                "data_notice": "Frozen Amazon Reviews 2023 snapshot; shopper requests are generated; payments are PayPal sandbox or mock."}

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

    class _Lazy:
        def __getattr__(self, name):
            return getattr(get_buyer(), name)

    app.include_router(world_router(_LazyReader(reader), runner or _BuyerBackedRunner(get_buyer), ledger_source=lambda: (get_payments(), state["ledger"])[1]))
    app.include_router(buyer_router(_Lazy()))
    return app


def _launch_authorized() -> bool:
    """The Qwen model is attached only when CRUCIBLE_MODEL_BACKEND=qwen AND Modal launch is authorized by the human-set gates."""
    if os.environ.get("CRUCIBLE_MODEL_BACKEND") != "qwen":
        return False
    from agents.model import InferenceError
    from agents.qwen_client import require_launch_authorization
    try:
        require_launch_authorization()
        return True
    except InferenceError:
        return False


class _LazyReader:
    """Defers the Elastic connection until the first world request, so the app boots (and /health passes) without it."""

    def __init__(self, reader=None):
        self._r = reader

    def __getattr__(self, name):
        if self._r is None:
            self._r = default_reader()
        return getattr(self._r, name)


configure_logging()
app = create_app()
