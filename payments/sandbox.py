"""PayPal Orders v2 backend (sandbox only): create -> get -> capture.

Verified against https://developer.paypal.com/api/orders/v2/ (spec v2.36) and
https://developer.paypal.com/api/rest/authentication/. Credentials come from the environment
and are never logged or put in exception text."""
import os
import time
from decimal import Decimal

import httpx

from payments.base import Capture
from payments.errors import (AmountMismatch, OrderNotApproved, OrderNotFound, PaymentDeclined,
                             PaymentError)

SANDBOX_URL = "https://api-m.sandbox.paypal.com"
_CENT = Decimal("0.01")
_ERRORS = {  # PayPal `issue`/`name` -> exception (error docs: .../reference/orders/v2/errors/)
    "ORDER_NOT_APPROVED": OrderNotApproved,
    "PAYER_ACTION_REQUIRED": OrderNotApproved,
    "RESOURCE_NOT_FOUND": OrderNotFound,
    "INVALID_RESOURCE_ID": OrderNotFound,
    "INSTRUMENT_DECLINED": PaymentDeclined,
    "TRANSACTION_REFUSED": PaymentDeclined,
}


def money(amount: Decimal) -> str:
    # ponytail: 2-dp currencies only (USD); zero-decimal ones (JPY) need their own exponent.
    if amount != amount.quantize(_CENT) or amount <= 0:
        raise ValueError(f"amount must be positive with at most 2 decimals, got {amount}")
    return f"{amount:.2f}"


class SandboxPayments:
    def __init__(self, client_id: str | None = None, client_secret: str | None = None,
                 client: httpx.Client | None = None,
                 return_url: str = "https://example.com/return",
                 cancel_url: str = "https://example.com/cancel"):
        env = os.environ.get("PAYPAL_ENV", "sandbox")
        if env != "sandbox":  # hard stop: this project never touches live money
            raise RuntimeError(f"PAYPAL_ENV must be 'sandbox', got {env!r}")
        self._auth = (client_id or os.environ["PAYPAL_CLIENT_ID"],
                      client_secret or os.environ["PAYPAL_CLIENT_SECRET"])
        self._http = client or httpx.Client(base_url=SANDBOX_URL, timeout=30)
        self._urls = (return_url, cancel_url)
        self._token: tuple[str, float] | None = None
        self._amounts: dict[str, tuple[Decimal, str]] = {}
        self._approval: dict[str, str] = {}

    # --- auth -------------------------------------------------------------------------------
    def _bearer(self, refresh: bool = False) -> str:
        if refresh or not self._token or time.monotonic() >= self._token[1]:
            r = self._http.post("/v1/oauth2/token", auth=self._auth,
                                data={"grant_type": "client_credentials"})
            if r.status_code != 200:
                raise PaymentError("AUTH_FAILED", http_status=r.status_code)
            body = r.json()
            self._token = (body["access_token"], time.monotonic() + body["expires_in"] - 60)
        return self._token[0]

    def _call(self, method: str, path: str, request_id: str | None = None,
              json: dict | None = None) -> dict:
        for attempt in (0, 1):
            headers = {"Authorization": f"Bearer {self._bearer(refresh=attempt == 1)}"}
            if request_id:
                headers["PayPal-Request-Id"] = request_id
            r = self._http.request(method, path, headers=headers, json=json)
            if r.status_code != 401 or attempt:
                break  # one retry on 401 = expired token
        if r.is_success:
            return r.json()
        try:
            e = r.json()
        except ValueError:
            e = {}
        issue = (e.get("details") or [{}])[0].get("issue")
        code = issue or e.get("name") or "HTTP_ERROR"
        exc = _ERRORS.get(code) or _ERRORS.get(e.get("name", ""), PaymentError)
        raise exc(code, e.get("message", ""), r.status_code, e.get("debug_id"))

    # --- PaymentsBackend --------------------------------------------------------------------
    def create_order(self, amount: Decimal, currency: str, idempotency_key: str) -> str:
        ctx = {"return_url": self._urls[0], "cancel_url": self._urls[1],
               "user_action": "PAY_NOW", "shipping_preference": "NO_SHIPPING"}
        order = self._call("POST", "/v2/checkout/orders", request_id=idempotency_key, json={
            "intent": "CAPTURE",
            "purchase_units": [{"custom_id": idempotency_key,  # ledger reconciliation
                                "amount": {"currency_code": currency, "value": money(amount)}}],
            "payment_source": {"paypal": {"experience_context": ctx}},
        })
        self._amounts[order["id"]] = (amount, currency)
        self._approval[order["id"]] = self._approve_link(order)
        return order["id"]

    def get_status(self, order_id: str) -> str:
        """CREATED | SAVED | APPROVED | VOIDED | COMPLETED | PAYER_ACTION_REQUIRED."""
        return self._call("GET", f"/v2/checkout/orders/{order_id}")["status"]

    def approval_url(self, order_id: str) -> str:
        """Buyer approval link. Secret-grade: hand to the approver, never log it."""
        return self._approval[order_id]

    def capture(self, order_id: str) -> Capture:
        try:  # stable request id => retries replay the same capture
            order = self._call("POST", f"/v2/checkout/orders/{order_id}/capture",
                               request_id=f"capture-{order_id}")
        except PaymentError as e:
            if e.code != "ORDER_ALREADY_CAPTURED":
                raise
            order = self._call("GET", f"/v2/checkout/orders/{order_id}")  # replay past retention
        cap = order["purchase_units"][0]["payments"]["captures"][0]
        amount, ccy = Decimal(cap["amount"]["value"]), cap["amount"]["currency_code"]
        if cap["status"] != "COMPLETED":
            raise PaymentDeclined(cap["status"], f"capture of {order_id} not completed")
        if order_id in self._amounts and self._amounts[order_id] != (amount, ccy):
            raise AmountMismatch("AMOUNT_MISMATCH", f"{self._amounts[order_id]} != {(amount, ccy)}")
        return Capture(order_id=order["id"], capture_id=cap["id"], amount=amount, currency=ccy,
                       status=cap["status"])

    @staticmethod
    def _approve_link(order: dict) -> str:
        # `payer-action` with payment_source.paypal.experience_context; `approve` on legacy shape
        links = {link["rel"]: link["href"] for link in order.get("links", [])}
        return links.get("payer-action") or links.get("approve", "")
