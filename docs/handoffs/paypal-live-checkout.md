# Handoff: PayPal live checkout (`feat/paypal-live-checkout`)

Base: `origin/main` 11fcb1f. Sandbox only; no production credentials or endpoints anywhere. Offline suite: 350 passed (live tests deselected). Secret scan: 0 findings.

## What is true now

| Area | State |
|---|---|
| Orders v2 backend (create/get/capture, idempotency, retries, typed redacted errors) | hardened, offline-verified against a stateful fake |
| Explicit-confirmation boundary in the buyer API | enforced and tested stage by stage |
| Duplicate-capture prevention | tested offline; **not yet measured against real PayPal** |
| Kernel buyer approval | allowlisted, authorization-gated, bounded, tested with a fake Kernel; **never run live** |
| Ledger | `payments/ledger.py`, sanitized, written by `GuardedPayments(ledger=...)` |
| Postman | 10-step sandbox flow + buyer chat stages |
| Live sandbox approval + capture | **NOT RUN**: buyer credentials missing, no user authorization |

No latency, approval or capture numbers exist for the live path. Earlier create/get medians (670/371 ms, 5 orders) are from the Day-1 spike.

## Run the live check (needs the user's go-ahead)

Add `PAYPAL_SANDBOX_BUYER_EMAIL` / `PAYPAL_SANDBOX_BUYER_PASSWORD` (sandbox *personal* account) to the env file, then:

```
CRUCIBLE_KERNEL_BUYER_APPROVAL_AUTHORIZED=1 \
uv run python -m scripts.paypal_live_check --env-file "<repo>/.env" --confirm-sandbox-run
```

`--no-kernel` stops at the approval URL (exit 5) and needs no buyer or Kernel variables. Exit codes: 0 ok, 3 config missing, 4 authorization missing, 5 approval blocked, 6 PayPal API, 7 Kernel, 8 assertion. Evidence is written to `docs/payments/paypal_live_check.json` (sanitized; review before committing, then `uv run python -m scripts.secret_scan`). Diagnostics today: exit 3 naming the two buyer variables.

## Contracts (all additive)

- `Capture.replayed`; `PaymentError.retryable`; `PaymentUnavailable`; new codes `CAPTURE_PENDING`, `CAPTURE_MISSING`, `TIMEOUT`, `NETWORK_ERROR`.
- Buyer events: `paypal_approval` + `order_id`, `pending_order_id`, `approval_required` (URL is null once approved); `receipt` + `payment_status`, `idempotency` (`created|replayed`); error code `payment_unavailable` (retry). Polling `GET /agent/runs/{id}` can append a new `paypal_approval` event when the buyer approves. `docs/api/**` regenerated (additive).
- `GuardedPayments(ledger=PaymentLedger(mode))`, `record_approval()`, `PendingOrder.task_id/backend_key`.

## Requests for others

- **Agent 4 (`api/main.py`)**: none required. Optional: build the sandbox `GuardedPayments` with `ledger=PaymentLedger("sandbox")` and expose `ledger.entries()` read-only if a real ledger endpoint is wanted (`/payments/ledger` in `api/world.py` still serves mock world data). `PaymentError` currently maps to 402 for every code including retryable `PaymentUnavailable`; a 503 for retryable ones would be more accurate.
- **Web**: `web/src/generated/samples.json` predates the new optional fields; the zod schema is not strict, so nothing breaks. Regenerate when convenient. Web should treat `payment_unavailable` as "confirm again" (safe: idempotent).

## Safety properties and where they are tested

- No capture without `user_confirmed: true`, fresh/unchanged quote, in-budget total: `tests/test_api_buyer.py`, `tests/test_payments_ledger.py`.
- Approval ≠ confirmation ≠ capture; create success ≠ approval: `test_each_stage_alone_never_captures_...`.
- One charge under retries/concurrent confirms: `test_repeated_and_concurrent_confirmation_charge_once`, `test_second_capture_with_a_different_request_id_...`.
- No secrets/bodies/debug ids in errors, ledger, evidence: contract, ledger, live-check tests.
- Kernel allowlist, challenge stop, cleanup, no capture in browser code: `tests/test_kernel_approver.py`.
- World/evolution runner still uses `MockPayments()` (`tests/test_world_runtime.py`).
- Known limit: `Capture.replayed` is detected in-process or via `ORDER_ALREADY_CAPTURED`; a replay in a fresh process within PayPal's request-id window returns the original capture and is not flagged. The ledger still shows one PayPal capture via `order_captures()`.
