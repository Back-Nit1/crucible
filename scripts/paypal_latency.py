"""Sandbox create + retrieve latency (no buyer needed). Creates N unpaid $1.00 sandbox orders; sanitized output.
  uv run python scripts/paypal_latency.py --env-file <.env> -n 5 --confirm-sandbox-run
Exit: 0 ok | 3 configuration missing | 4 authorization missing | 6 PayPal API failure."""
import argparse
import os
import statistics
import sys
import time
import uuid
from decimal import Decimal

sys.path.insert(0, "scripts")
from _env import load  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--env-file", required=True)
ap.add_argument("-n", type=int, default=5)
ap.add_argument("--confirm-sandbox-run", action="store_true")
a = ap.parse_args()
load(a.env_file, {"PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "PAYPAL_ENV"})
missing = [k for k in ("PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET") if not os.environ.get(k)]
if os.environ.get("PAYPAL_ENV") != "sandbox":
    missing.append("PAYPAL_ENV(must be exactly 'sandbox')")
if missing:
    print({"status": "configuration_missing", "missing_env_names": missing})
    sys.exit(3)
if not a.confirm_sandbox_run:
    print({"status": "authorization_missing", "required": ["--confirm-sandbox-run"]})
    sys.exit(4)

from payments.errors import PaymentError  # noqa: E402
from payments.sandbox import SandboxPayments  # noqa: E402

sb = SandboxPayments()
create, get = [], []
try:
    t = time.perf_counter()
    sb._bearer()
    print("oauth_ms", round((time.perf_counter() - t) * 1000))
    for i in range(a.n):
        t = time.perf_counter(); oid = sb.create_order(Decimal("1.00"), "USD", uuid.uuid4().hex); create.append(time.perf_counter() - t)
        t = time.perf_counter(); st = sb.get_status(oid); get.append(time.perf_counter() - t)
        print(i, "create_ms", round(create[-1] * 1000), "get_ms", round(get[-1] * 1000), "status", st,
              "has_approval_link", sb.approval_url(oid).startswith("https://"))
except PaymentError as e:
    print({"status": "paypal_api_failure", "code": e.code, "http_status": e.http_status, "retryable": e.retryable})
    sys.exit(6)
for name, v in (("create", create), ("get", get)):
    print(name, "median_ms", round(statistics.median(v) * 1000), "max_ms", round(max(v) * 1000))
