"""Repeat create -> Kernel buyer approval -> capture N times, with latency. Sandbox only, $1.00 each. Sanitized output.
  CRUCIBLE_KERNEL_BUYER_APPROVAL_AUTHORIZED=1 uv run python scripts/paypal_kernel_e2e.py --env-file <.env> -n 3 --confirm-sandbox-run
Prefer `python -m scripts.paypal_live_check` for the single canonical verification; this is for latency samples.
Exit: 0 ok | 3 configuration missing | 4 authorization missing | 5 approval blocked | 6 PayPal failure | 7 Kernel failure."""
import argparse
import os
import sys
import time
import uuid
from decimal import Decimal

sys.path.insert(0, "scripts")
from _env import load  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--env-file", required=True)
ap.add_argument("-n", type=int, default=1)
ap.add_argument("--confirm-sandbox-run", action="store_true")
a = ap.parse_args()
NEEDED = ["PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "KERNEL_API_KEY", "PAYPAL_SANDBOX_BUYER_EMAIL", "PAYPAL_SANDBOX_BUYER_PASSWORD"]
load(a.env_file, set(NEEDED) | {"PAYPAL_ENV"})
missing = [k for k in NEEDED if not os.environ.get(k)]
if os.environ.get("PAYPAL_ENV") != "sandbox":
    missing.append("PAYPAL_ENV(must be exactly 'sandbox')")
if missing:
    print({"status": "configuration_missing", "missing_env_names": missing})
    sys.exit(3)
need = (["--confirm-sandbox-run"] if not a.confirm_sandbox_run else []) + \
       (["CRUCIBLE_KERNEL_BUYER_APPROVAL_AUTHORIZED=1"] if os.environ.get("CRUCIBLE_KERNEL_BUYER_APPROVAL_AUTHORIZED") != "1" else [])
if need:
    print({"status": "authorization_missing", "required": need})
    sys.exit(4)

from payments.errors import PaymentError  # noqa: E402
from payments.kernel_approver import ApprovalBlocked, KernelApprover, KernelError  # noqa: E402
from payments.sandbox import SandboxPayments  # noqa: E402

sb = SandboxPayments()
ap_ = KernelApprover(sb, os.environ["PAYPAL_SANDBOX_BUYER_EMAIL"], os.environ["PAYPAL_SANDBOX_BUYER_PASSWORD"])
for i in range(a.n):
    try:
        t0 = time.perf_counter()
        oid = sb.create_order(Decimal("1.00"), "USD", uuid.uuid4().hex)
        t1 = time.perf_counter()
        print(i, "created", sb.get_status(oid), "create_ms", round((t1 - t0) * 1000))
        ap_.approve(oid)
        t2 = time.perf_counter()
        cap = sb.capture(oid)
        t3 = time.perf_counter()
    except ApprovalBlocked as e:
        print(i, "BLOCKED", e, "- stopping"); sys.exit(5)
    except KernelError as e:
        print(i, "KERNEL_FAILURE", e, "- stopping"); sys.exit(7)
    except PaymentError as e:
        print(i, "PAYPAL_FAILURE", e.code, e.http_status, "- stopping"); sys.exit(6)
    print(i, "approve_ms", round((t2 - t1) * 1000), {k: round(v * 1000) for k, v in ap_.timings.items()},
          "capture_ms", round((t3 - t2) * 1000), "capture", cap.status, cap.amount, cap.currency,
          "final_status", sb.get_status(oid), "order", oid)
