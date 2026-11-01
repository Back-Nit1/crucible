"""Phase 8: ONE $1 PayPal *sandbox* flow: create -> Kernel buyer approval -> capture -> verify -> capture retry.
  uv run python -m scripts.paypal_live_check --env-file <.env>   # needs PAYPAL_CLIENT_ID/SECRET, KERNEL_API_KEY,
                                                                 # PAYPAL_SANDBOX_BUYER_EMAIL/PASSWORD in that file
Separate from world runs (those are mock-only). Stops at the first CAPTCHA/bot check (never works around it).
Writes sanitized results only (ids, status, amounts, timings - no credentials, no approval URL) to
docs/spikes/results/paypal_live_check.json."""
import argparse
import json
import sys
import time
import uuid
from decimal import Decimal
from pathlib import Path

from scripts._env import load

NEEDED = ["PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "KERNEL_API_KEY", "PAYPAL_SANDBOX_BUYER_EMAIL", "PAYPAL_SANDBOX_BUYER_PASSWORD"]
OUT = Path("docs/spikes/results/paypal_live_check.json")


def ms(a, b):
    return round((b - a) * 1000)


def main(argv=None) -> int:
    import os
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file", required=True)
    a = ap.parse_args(argv)
    load(a.env_file, set(NEEDED) | {"PAYPAL_ENV"})
    missing = [k for k in NEEDED if not os.environ.get(k)]
    if missing:
        print(json.dumps({"status": "blocked", "missing_env_names": missing}))
        return 3
    from payments.kernel_approver import ApprovalBlocked, KernelApprover
    from payments.sandbox import SandboxPayments
    sb = SandboxPayments()
    ap_ = KernelApprover(sb, os.environ["PAYPAL_SANDBOX_BUYER_EMAIL"], os.environ["PAYPAL_SANDBOX_BUYER_PASSWORD"])
    key, res = uuid.uuid4().hex, {"environment": "sandbox", "amount": "1.00", "currency": "USD"}
    t0 = time.perf_counter()
    oid = sb.create_order(Decimal("1.00"), "USD", key)
    t1 = time.perf_counter()
    res |= {"order_id": oid, "status_after_create": sb.get_status(oid), "create_ms": ms(t0, t1)}
    try:
        res["status_after_approval"] = ap_.approve(oid)
    except ApprovalBlocked as e:
        res |= {"status": "stopped_challenge", "detail": str(e)}
        print(json.dumps(res))
        return 2
    t2 = time.perf_counter()
    cap = sb.capture(oid)
    t3 = time.perf_counter()
    again = sb.capture(oid)  # retry: must replay the same capture, not charge twice
    order = sb._call("GET", f"/v2/checkout/orders/{oid}")
    captures = order["purchase_units"][0]["payments"]["captures"]
    res |= {"approval_ms": ms(t1, t2), "approval_breakdown_ms": {k: round(v * 1000) for k, v in ap_.timings.items()},
            "capture_ms": ms(t2, t3), "capture_id": cap.capture_id, "capture_amount": str(cap.amount),
            "capture_currency": cap.currency, "final_order_status": order["status"],
            "retry_same_capture_id": again.capture_id == cap.capture_id, "captures_on_order": len(captures),
            "no_duplicate_charge": len(captures) == 1 and again.capture_id == cap.capture_id,
            "amount_matches": cap.amount == Decimal("1.00") and cap.currency == "USD",
            "status": "passed" if order["status"] == "COMPLETED" and len(captures) == 1 else "failed"}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, indent=2, sort_keys=True) + "\n")
    print(json.dumps(res, indent=2))
    return 0 if res["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
