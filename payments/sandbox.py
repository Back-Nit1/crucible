"""PayPal Orders v2 backend (sandbox only): create -> get -> capture.

Verified against https://developer.paypal.com/api/orders/v2/ (spec v2.36) and
https://developer.paypal.com/api/rest/authentication/. Credentials come from the environment
and are never logged or put in exception text."""
import os
import time
from decimal import Decimal

import httpx

from payments.base import Capture
from payments.errors import (RETRYABLE_STATUSES, AmountMismatch, OrderNotApproved, OrderNotFound,
                             PaymentDeclined, PaymentError, PaymentUnavailable)

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
                 cancel_url: str = "https://example.com/cancel", retries: int = 2,
                 sleep=time.sleep):
        env = os.environ.get("PAYPAL_ENV", "sandbox")
        if env != "sandbox":  # hard stop: this project never touches live money
            raise RuntimeError(f"PAYPAL_ENV must be 'sandbox', got {env!r}")
        self._auth = (client_id or os.environ["PAYPAL_CLIENT_ID"],
                      client_secret or os.environ["PAYPAL_CLIENT_SECRET"])
        self._http = client or httpx.Client(base_url=SANDBOX_URL, timeout=30)
        self._urls = (return_url, cancel_url)
        self._retries, self._sleep = retries, sleep
        self._token: tuple[str, float] | None = None
        self._captured: set[str] = set()
        self._amounts: dict[str, tuple[Decimal, str]] = {}
        self._approval: dict[str, str] = {}

    # --- auth -------------------------------------------------------------------------------
    def _send(self, method: str, path: str, **kw) -> httpx.Response:
        """One HTTP call with bounded retry on transient failures (timeout, network, 429/5xx).
        Only used with idempotent calls: GET, token, and POSTs that carry a stable PayPal-Request-Id."""
        for attempt in range(self._retries + 1):
            try:
                r = self._http.request(method, path, **kw)
                if r.status_code not in RETRYABLE_STATUSES or attempt == self._retries:
                    return r
            except httpx.TimeoutException:
                if attempt == self._retries:
                    raise PaymentUnavailable("TIMEOUT") from None
            except httpx.TransportError:
                if attempt == self._retries:
                    raise PaymentUnavailable("NETWORK_ERROR") from None
            self._sleep(0.25 * 2 ** attempt)
        raise AssertionError("unreachable")  # pragma: no cover

    def _bearer(self, refresh: bool = False) -> str:
        if refresh or not self._token or time.monotonic() >= self._token[1]:
            r = self._send("POST", "/v1/oauth2/token", auth=self._auth,
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
            r = self._send(method, path, headers=headers, json=json)
            if r.status_code != 401 or attempt:
                break  # one retry on 401 = expired token
        if r.is_success:
            return r.json()
        try:
            e = r.json()
        except ValueError:
            e = {}
        if not isinstance(e, dict):
            e = {}
        issue = (e.get("details") or [{}])[0].get("issue")
        code = issue or e.get("name") or "HTTP_ERROR"
        exc = _ERRORS.get(code) or _ERRORS.get(e.get("name", ""), PaymentUnavailable if r.status_code in RETRYABLE_STATUSES else PaymentError)
        raise exc(code, "", r.status_code, e.get("debug_id"))  # PayPal's free-text message is never propagated

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
        replayed = order_id in self._captured
        try:  # stable request id => retries replay the same capture
            order = self._call("POST", f"/v2/checkout/orders/{order_id}/capture",
                               request_id=f"capture-{order_id}", json={})  # PayPal 415s a body-less capture (live-verified)
        except PaymentError as e:
            if e.code != "ORDER_ALREADY_CAPTURED":
                raise
            order, replayed = self._call("GET", f"/v2/checkout/orders/{order_id}"), True  # replay past retention
        try:
            cap = order["purchase_units"][0]["payments"]["captures"][0]
            amount, ccy = Decimal(cap["amount"]["value"]), cap["amount"]["currency_code"]
        except (KeyError, IndexError, TypeError, ArithmeticError):
            raise PaymentError("CAPTURE_MISSING", f"no usable capture on order {order_id}") from None
        if cap["status"] == "PENDING":
            raise PaymentError("CAPTURE_PENDING", f"capture of {order_id} is pending")
        if cap["status"] != "COMPLETED":
            raise PaymentDeclined(cap["status"], f"capture of {order_id} not completed")
        if order_id in self._amounts and self._amounts[order_id] != (amount, ccy):
            raise AmountMismatch("AMOUNT_MISMATCH", f"{self._amounts[order_id]} != {(amount, ccy)}")
        self._captured.add(order_id)
        return Capture(order_id=order["id"], capture_id=cap["id"], amount=amount, currency=ccy,
                       status=cap["status"], replayed=replayed)

    # --- verification probes (live-check script and tests; never used by checkout) -------------------
    def order_captures(self, order_id: str) -> list[tuple[str, Decimal, str, str]]:
        """(capture_id, amount, currency, status) for every capture PayPal records on the order: the ground truth."""
        order = self._call("GET", f"/v2/checkout/orders/{order_id}")
        caps = (order.get("purchase_units") or [{}])[0].get("payments", {}).get("captures", [])
        return [(c["id"], Decimal(c["amount"]["value"]), c["amount"]["currency_code"], c["status"]) for c in caps]

    def duplicate_capture_code(self, order_id: str) -> str:
        """Capture again under a NEW PayPal-Request-Id (what a buggy client would do). Expected result:
        'ORDER_ALREADY_CAPTURED'. 'CAPTURED_AGAIN' means PayPal accepted a second capture."""
        try:
            self._call("POST", f"/v2/checkout/orders/{order_id}/capture", request_id=f"dup-probe-{order_id}-{time.time_ns()}", json={})
        except PaymentError as e:
            return e.code
        return "CAPTURED_AGAIN"

    @staticmethod
    def _approve_link(order: dict) -> str:
        # `payer-action` with payment_source.paypal.experience_context; `approve` on legacy shape
        links = {link["rel"]: link["href"] for link in order.get("links", [])}
        return links.get("payer-action") or links.get("approve", "")
