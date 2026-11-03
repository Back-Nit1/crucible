# Spike: PayPal sandbox checkout + Agent Toolkit + Kernel approval (Day-1 checks 1–3)

Status: **PARTIAL — offline hardening complete (branch `feat/paypal-live-checkout`); buyer approval and capture still not run live** (no sandbox buyer credentials and no user authorization for a live run; see Blockers and section 7).
Original spike branch: `feat/paypal-kernel-day1`. Sandbox only; no live credentials. No tokens, approval URLs, cookies or passwords appear below.

## 1. OAuth (verified live)

Docs: <https://developer.paypal.com/api/rest/authentication/>

```
python scripts/paypal_oauth_check.py <env-file>
status 200 ms 806 keys [access_token, app_id, expires_in, nonce, scope, token_type] token_type Bearer expires_in 32399 access_token_len 97
```

`POST https://api-m.sandbox.paypal.com/v1/oauth2/token`, HTTP Basic (client id:secret), `grant_type=client_credentials`.

## 2. Orders v2 (`payments/sandbox.py`)

Docs: <https://developer.paypal.com/api/orders/v2/> (OpenAPI v2.36, `schema.json`), errors: <https://developer.paypal.com/api/rest/reference/orders/v2/errors/>

Verified against the spec: `POST /v2/checkout/orders` (header `PayPal-Request-Id`, body `intent`, `purchase_units[].amount.{currency_code,value}`, `purchase_units[].custom_id`, `payment_source.paypal.experience_context.{return_url,cancel_url,user_action,shipping_preference}`), `GET /v2/checkout/orders/{id}`, `POST /v2/checkout/orders/{id}/capture` (header `PayPal-Request-Id`). Order status enum: `CREATED, SAVED, APPROVED, VOIDED, COMPLETED, PAYER_ACTION_REQUIRED`. Capture status enum: `COMPLETED, DECLINED, PARTIALLY_REFUNDED, PENDING, REFUNDED, FAILED`. With `payment_source.paypal.experience_context` the create response is `PAYER_ACTION_REQUIRED` with a `payer-action` link (the legacy shape uses `approve`; both handled).

Not verifiable from the spec (numeric HTTP status per error issue is not listed on the errors page): error mapping keys on `details[0].issue` / `name`, not on status code.

Behaviour:
- Money is `Decimal` end to end, formatted `"%.2f"`; >2 decimals, zero, or negative raises before any API call.
- Create uses the guard idempotency key as `PayPal-Request-Id` (and `custom_id`, for ledger reconciliation). Capture uses `capture-{order_id}`; if PayPal answers `ORDER_ALREADY_CAPTURED` the capture is rebuilt from `GET`.
- Capture amount is compared with the created amount (`AmountMismatch`); non-`COMPLETED` capture raises `PaymentDeclined`.
- `PAYPAL_ENV != sandbox` raises at construction.

Live create + retrieve (5 orders, `scripts/paypal_latency.py`, token acquisition excluded):

| step | median | max |
|---|---|---|
| create order | 670 ms | 876 ms |
| get order | 371 ms | 457 ms |

All 5 returned `PAYER_ACTION_REQUIRED` with a payer-action link. No rate-limit response seen at this volume (sample too small to establish headroom).

## 3. Contract tests

`tests/test_payments_contract.py` runs one scenario set against `MockPayments(auto_approve=False)` and `SandboxPayments` over a stateful fake of Orders v2 (`httpx.MockTransport`): exact amount, inexact-amount rejection, idempotent create/capture, status progression, error mapping (not approved, not found). Sandbox-only: wire headers, 401 token refresh, declined capture, already-captured replay, amount mismatch, live-env refusal, budget rejection with **zero** HTTP calls, no capture call without confirmation. The fake follows spec shapes but is **not** PayPal; live sandbox behaviour is covered by section 2 and section 5.

`MockPayments` gained `auto_approve` (default `True`, keeps bulk-training behaviour), `approve()`, `get_status()`, `approval_url()`.

## 4. PayPal Agent Toolkit / MCP (check 2)

Docs: <https://developer.paypal.com/ai-tools/agent-tools>, <https://developer.paypal.com/tools/mcp-server/>, <https://github.com/paypal/agent-toolkit>

| Need | Toolkit | Verdict |
|---|---|---|
| create order | `create_order` (`items[{name,quantity,unit_price}]`, `currency`); return value undocumented | partial: no `custom_id`/idempotency header or approval link documented |
| get order status | `get_order` takes `payment_id`, described as "a specific payment" | not confirmed as order-by-id |
| capture | `pay_order` (`order_id`) | covered |
| buyer approval | none | **not covered** |
| refund | `create_refund`, `get_refund` | covered (unused) |

Local server: `npx -y @paypal/mcp --tools=all`, env `PAYPAL_ACCESS_TOKEN`, `PAYPAL_ENVIRONMENT=SANDBOX`; remote `https://mcp.sandbox.paypal.com`. Third-party issue <https://github.com/paypal/agent-toolkit/issues/95> (unverified by us) reports no human gate or spend bound on capture. **Decision: no `agent_toolkit.py` adapter** — required actions (idempotent create with approval link, order status, approval) are not confirmed.

## 5. Kernel buyer approval (check 1a)

Docs: <https://www.kernel.sh/docs/quickstart>, <https://www.kernel.sh/docs/api-reference/browsers/create-a-browser-session.md>, <https://www.kernel.sh/docs/browsers/replays.md>. SDK `kernel==0.139.0` (`pip install kernel`; optional extra here). Used: `browsers.create(timeout_seconds=)`, `browsers.playwright.execute(id, code=, timeout_sec=)`, `browsers.delete_by_id`. Not set: `stealth`, `proxy`, any CAPTCHA feature.

Credential-free probe (`scripts/kernel_probe.py`): a default Kernel browser (`stealth=False`, `headless=False`, create ≈ 274 ms) opened our own sandbox approval page. Result: host `www.sandbox.paypal.com`, path `/checkoutnow`, title "Log in to your PayPal account"; visible inputs `#email` (`login_email`), `#password`, buttons `#btnNext`, `#btnLogin`; a `www.recaptcha.net` frame is present on the page and two captcha text inputs exist; no block text detected. Order stayed `PAYER_ACTION_REQUIRED`. **Whether PayPal challenges the login itself is unknown until credentials are used.**

`payments/kernel_approver.py` logs in, clicks the review/confirm button, polls order status to `APPROVED`, and raises `ApprovalBlocked` (stopping the run) on any challenge frame/text or unexpected step.

## 6. Hardening on `feat/paypal-live-checkout` (offline-verified; fake Orders v2, not PayPal)

- **Backend (`payments/sandbox.py`)**: transient failures (timeout, network, 429/5xx) retry twice with backoff and the *same* `PayPal-Request-Id`, so a retried create/capture can never produce a second order/charge. Exhausted retries raise `PaymentUnavailable` (`TIMEOUT` / `NETWORK_ERROR`, `.retryable`). PayPal's free-text `message` is never propagated; `debug_id` is an attribute only (not in `str`/`repr`). Pending (`CAPTURE_PENDING`, retryable) and missing captures are typed. `Capture.replayed` marks a returned existing capture. Probes `order_captures()` / `duplicate_capture_code()` exist for verification only.
- **Ledger (`payments/ledger.py`)**: `proposal | confirmation | approval | capture | failure` rows with mode, time, amount/currency, order/capture ids, hashed idempotency key, outcome (`created|replayed`), latency, failure code, run/generation id. `extra="forbid"`: no field can carry credentials, URLs, bodies, debug ids or payer data. Written by `GuardedPayments` (pass `ledger=`).
- **Buyer API (`api/buyer.py`)**: stages stay separate. `paypal_approval` events carry `order_id`, `pending_order_id`, `approval_required`; the approval URL is dropped once the order is APPROVED. `GET /agent/runs/{id}` surfaces buyer approval as a new event (never captures). Confirm is serialized per run; a timeout is `payment_unavailable` (retryable, run stays `awaiting_confirmation`); not-approved stays recoverable; a dropped (stale/changed) order is a typed 404. `receipt` adds `payment_status` and `idempotency`.
- **Kernel (`payments/kernel_approver.py`)**: requires `CRUCIBLE_KERNEL_BUYER_APPROVAL_AUTHORIZED=1` before any session; navigates only to `https://www.sandbox.paypal.com` / `sandbox.paypal.com` (checked before the browser exists and after every step inside it); stops on CAPTCHA, identity/2FA text or unexpected host; no capture in browser code; session always deleted (`cleanup_ok`); failures are `ApprovalBlocked` (challenge) or `KernelError` (transport), both scrubbed of buyer credentials. Docs re-verified: `browsers.playwright.execute(session_id, code=, timeout_sec=)` returns `success/result/error`; `browsers.delete_by_id(session_id)`.
- **Postman**: 10-step sandbox flow + buyer start/poll/confirm with expected-failure examples; capture requests are redirected to a bogus id unless the order is APPROVED.

## 7. The canonical live command 

```
CRUCIBLE_KERNEL_BUYER_APPROVAL_AUTHORIZED=1 \
uv run python -m scripts.paypal_live_check --env-file <.env> --confirm-sandbox-run [--no-kernel]
```

$1.00 USD, sandbox, once. Steps timed individually: oauth, create_order, create_replay, get_order, kernel_approval, get_order_after_approval, capture, capture_record, capture_replay, duplicate_capture. Asserts exactly one PayPal capture on the order after a second capture under a new request id (the response code is recorded; live PayPal answered 2xx while still recording one capture). Exit codes: `0` success, `3` configuration missing (names only), `4` authorization missing, `5` approval blocked (challenge, or `--no-kernel`), `6` PayPal API failure, `7` Kernel failure, `8` assertion failure. Per-run evidence goes to `docs/payments/paypal_live_check.json` (the script overwrites it each run; the committed file is a hand-assembled per-run summary, see section 8).

## 8. Live results, 2026-11-02 (sandbox, $1.00 USD, 8 of 8 authorized runs used)

Target of 5 consecutive passes was **not reached**. Reliability is therefore **not established**.

| Run | Code state | Result | Cause |
|---|---|---|---|
| 1-3 | role-based buttons + Next retry | approval failed | Kernel browser got the login page in **Portuguese** (`placeholder="Senha"`); English `Next`/`Log In` matchers never matched |
| 4 | + `Accept-Language: en-US`, pt labels | approval failed | Log In button not found (page text not captured then) |
| 5 | same | flagged `after_review:unexpected_host` | pay click redirected to the merchant `return_url` (example.com), wrongly treated as a challenge. Order status not checked |
| 6 | + return_url fix, diagnostics | approval failed | page back at the email step; Log In never visible. Cause not identified |
| 7 | + whole-login retry | **approval + capture OK** (approval 14.7 s, capture 1.3 s, replay same capture id, exactly 1 capture on the order); script exit 8 | script asserted `ORDER_ALREADY_CAPTURED` for the duplicate; PayPal answered 2xx but recorded 1 capture. Assertion corrected afterwards |
| 8 | same as 7 | approval failed | page at the email step; Log In never visible. Cause not identified |

Observed: 1 fully successful flow in 8 runs (run 7), plus 1 earlier success in the user's session (approval 13.1 s, capture 1.2 s). With the final code: 1 pass, 1 fail. No CAPTCHA or 2FA was ever seen. Open: why the form returns to the email step after the password is filled (suspect hydration race or a client-side reset); needs a screenshot/trace on the next authorized run. Judges approve by hand in PayPal's own page; the Kernel approver is for automated checks and the video only.

## Blockers

- Kernel login automation is flaky (see section 8); the 8-run authorization is spent.
