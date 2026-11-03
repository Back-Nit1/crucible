"""ONE canonical $1.00 PayPal *sandbox* flow, step by step, with latency per step and a sanitized ledger:
  oauth -> create -> get -> approval url -> Kernel buyer approval -> approved? -> capture -> capture record
  -> idempotent replay -> duplicate capture (new request id) -> ledger

  uv run python -m scripts.paypal_live_check --env-file <.env> --confirm-sandbox-run [--no-kernel]

Needs PAYPAL_CLIENT_ID/SECRET, PAYPAL_ENV=sandbox (exactly), and unless --no-kernel: KERNEL_API_KEY,
PAYPAL_SANDBOX_BUYER_EMAIL/PASSWORD and CRUCIBLE_KERNEL_BUYER_APPROVAL_AUTHORIZED=1. Values are never printed.
Stops at the first CAPTCHA/bot check (never works around it). Never captures by browser: the server captures.

Exit codes: 0 success | 3 configuration missing | 4 authorization missing | 5 approval blocked
            6 PayPal API failure | 7 Kernel failure | 8 assertion failure
Writes sanitized evidence (ids, statuses, amounts, timings, hashed key; no credentials/URLs/bodies) to
docs/payments/paypal_live_check.json only when external calls were made."""
import argparse
import json
import os
import sys
import time
import uuid
from decimal import Decimal
from pathlib import Path

from scripts._env import load

OK, CONFIG, AUTH, BLOCKED, PAYPAL, KERNEL, ASSERT = 0, 3, 4, 5, 6, 7, 8
BASE_ENV = ["PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "PAYPAL_ENV"]
KERNEL_ENV = ["KERNEL_API_KEY", "PAYPAL_SANDBOX_BUYER_EMAIL", "PAYPAL_SANDBOX_BUYER_PASSWORD"]
NEEDED = BASE_ENV + KERNEL_ENV  # kept for callers/tests: the full list names
AMOUNT, CURRENCY = Decimal("1.00"), "USD"
OUT = Path("docs/payments/paypal_live_check.json")


class Steps:
    """Runs named steps, timing each; a step that raises is recorded as failed and re-raised."""

    def __init__(self):
        self.rows: list[dict] = []

    def run(self, name, fn):
        t = time.perf_counter()
        try:
            out = fn()
        except BaseException:
            self.rows.append({"step": name, "ms": round((time.perf_counter() - t) * 1000), "ok": False})
            raise
        self.rows.append({"step": name, "ms": round((time.perf_counter() - t) * 1000), "ok": True})
        return out


def check(cond, what):
    if not cond:
        raise AssertionError(what)


def run_flow(sb, approve, ledger, steps: Steps, res: dict) -> None:
    """The flow itself. `approve(order_id)` is Kernel (live) or None (--no-kernel). Raises typed errors."""
    from payments.kernel_approver import check_approval_url
    key = uuid.uuid4().hex
    steps.run("oauth", sb._bearer)
    t = time.perf_counter()
    oid = steps.run("create_order", lambda: sb.create_order(AMOUNT, CURRENCY, key))
    ledger.record("proposal", idempotency_key=key, order_ref=oid, amount=AMOUNT, currency=CURRENCY,
                  idempotency_outcome="created", latency_ms=round((time.perf_counter() - t) * 1000))
    res["order_id"] = oid
    check(steps.run("create_replay", lambda: sb.create_order(AMOUNT, CURRENCY, key)) == oid, "create replay returned another order")
    status = steps.run("get_order", lambda: sb.get_status(oid))
    res["status_after_create"] = status
    check(status in ("CREATED", "PAYER_ACTION_REQUIRED"), f"unexpected status after create: {status}")
    check_approval_url(sb.approval_url(oid))  # allowlisted sandbox host, never printed
    res["approval_url_allowlisted"] = True
    if approve is None:
        res["status"] = "approval_required"
        raise_blocked("approval needed: rerun without --no-kernel, or approve the order as the sandbox buyer")
    steps.run("kernel_approval", lambda: approve(oid))
    status = steps.run("get_order_after_approval", lambda: sb.get_status(oid))
    check(status == "APPROVED", f"order not APPROVED after approval: {status}")
    res["status_after_approval"] = status
    ledger.record("approval", order_ref=oid, status=status, amount=AMOUNT, currency=CURRENCY)
    ledger.record("confirmation", order_ref=oid, amount=AMOUNT, currency=CURRENCY)  # --confirm-sandbox-run
    t = time.perf_counter()
    cap = steps.run("capture", lambda: sb.capture(oid))
    ledger.record("capture", order_ref=oid, capture_ref=cap.capture_id, status=cap.status, amount=cap.amount, currency=cap.currency,
                  idempotency_key=key, idempotency_outcome="replayed" if cap.replayed else "created",
                  latency_ms=round((time.perf_counter() - t) * 1000))
    check((cap.amount, cap.currency, cap.status) == (AMOUNT, CURRENCY, "COMPLETED"), "capture amount/currency/status mismatch")
    records = steps.run("capture_record", lambda: sb.order_captures(oid))
    check(len(records) == 1 and records[0][0] == cap.capture_id and records[0][3] == "COMPLETED", "PayPal does not show exactly our one capture")
    again = steps.run("capture_replay", lambda: sb.capture(oid))
    ledger.record("capture", order_ref=oid, capture_ref=again.capture_id, status=again.status, amount=again.amount,
                  currency=again.currency, idempotency_outcome="replayed" if again.replayed else "created")
    check(again.capture_id == cap.capture_id and again.replayed, "replay did not return the same capture")
    dup = steps.run("duplicate_capture", lambda: sb.duplicate_capture_code(oid))
    after = sb.order_captures(oid)
    res |= {"capture_id": cap.capture_id, "capture_amount": str(cap.amount), "capture_currency": cap.currency,
            "captures_on_order": len(after), "replay_same_capture_id": again.capture_id == cap.capture_id,
            "duplicate_capture_result": dup, "final_order_status": sb.get_status(oid)}
    # Live 2026-11-02: PayPal may answer a second capture 2xx ("CAPTURED_AGAIN") yet still record ONE capture; the order's own
    # capture list, not the response code, is the proof of no double charge.
    check(len(after) == 1, f"duplicate capture created a second charge ({dup}, {len(after)} captures)")
    check(len(ledger.captures()) == 1, "ledger shows more than one charge")


def raise_blocked(msg):
    from payments.kernel_approver import ApprovalBlocked
    raise ApprovalBlocked(msg)


def execute(sb, approve, ledger, out: Path | None = OUT) -> tuple[dict, int]:
    from payments.errors import PaymentError
    from payments.kernel_approver import ApprovalBlocked, ApprovalNotAuthorized, KernelError
    steps, res = Steps(), {"environment": "sandbox", "amount": str(AMOUNT), "currency": CURRENCY, "mode": "sandbox"}
    code, status = OK, "passed"
    try:
        run_flow(sb, approve, ledger, steps, res)
    except ApprovalNotAuthorized as e:
        code, status, res["detail"] = AUTH, "authorization_missing", str(e)
    except ApprovalBlocked as e:
        code, status, res["detail"] = BLOCKED, res.get("status", "approval_blocked"), str(e)
    except KernelError as e:
        code, status, res["detail"] = KERNEL, "kernel_failure", str(e)
    except PaymentError as e:
        code, status, res["detail"] = PAYPAL, "paypal_api_failure", f"{e.code} http={e.http_status} retryable={e.retryable}"
    except AssertionError as e:
        code, status, res["detail"] = ASSERT, "assertion_failed", str(e)
    res |= {"status": status, "exit_code": code, "steps": steps.rows,
            "total_ms": sum(r["ms"] for r in steps.rows),
            "ledger": [e.model_dump(mode="json", exclude_none=True) for e in ledger.entries()]}
    if out is not None and steps.rows:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(res, indent=2, sort_keys=True) + "\n")
    return res, code


def main(argv=None, *, backend=None, approve=None, out: Path | None = OUT) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file", required=True)
    ap.add_argument("--confirm-sandbox-run", action="store_true", help="explicit go-ahead for the $1.00 sandbox run")
    ap.add_argument("--no-kernel", action="store_true", help="stop after the approval URL (human approves the order)")
    a = ap.parse_args(argv)
    load(a.env_file, set(NEEDED))
    need = BASE_ENV + ([] if a.no_kernel else KERNEL_ENV)
    missing = [k for k in need if not os.environ.get(k)]
    if os.environ.get("PAYPAL_ENV") != "sandbox":
        missing = [m for m in missing if m != "PAYPAL_ENV"] + ["PAYPAL_ENV(must be exactly 'sandbox')"]  # name only
    if missing:
        print(json.dumps({"status": "configuration_missing", "missing_env_names": missing}))
        return CONFIG
    unauthorized = ([] if a.confirm_sandbox_run else ["--confirm-sandbox-run"]) + \
                   ([] if a.no_kernel or os.environ.get("CRUCIBLE_KERNEL_BUYER_APPROVAL_AUTHORIZED") == "1"
                    else ["CRUCIBLE_KERNEL_BUYER_APPROVAL_AUTHORIZED=1"])
    if unauthorized:
        print(json.dumps({"status": "authorization_missing", "required": unauthorized}))
        return AUTH
    from payments.ledger import PaymentLedger
    from payments.sandbox import SandboxPayments
    sb = backend or SandboxPayments()
    if approve is None and not a.no_kernel:
        from payments.kernel_approver import KernelApprover
        approve = KernelApprover(sb, os.environ["PAYPAL_SANDBOX_BUYER_EMAIL"], os.environ["PAYPAL_SANDBOX_BUYER_PASSWORD"]).approve
    res, code = execute(sb, approve, PaymentLedger("sandbox"), out)
    print(json.dumps(res, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
