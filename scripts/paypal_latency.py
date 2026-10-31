"""Day-1 check 3: create + retrieve latency on the sandbox (no buyer needed). Sanitized output."""
import statistics, sys, time, uuid
sys.path.insert(0, "scripts")
from decimal import Decimal
from _env import load
load(sys.argv[1], {"PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "PAYPAL_ENV"})
from payments.sandbox import SandboxPayments

n = int(sys.argv[2])
sb = SandboxPayments()
sb._bearer()  # token cost reported separately
create, get = [], []
for i in range(n):
    t = time.perf_counter(); oid = sb.create_order(Decimal("1.00"), "USD", uuid.uuid4().hex); create.append(time.perf_counter() - t)
    t = time.perf_counter(); st = sb.get_status(oid); get.append(time.perf_counter() - t)
    print(i, "create_ms", round(create[-1] * 1000), "get_ms", round(get[-1] * 1000), "status", st,
          "has_approval_link", sb.approval_url(oid).startswith("https://"))
for name, v in (("create", create), ("get", get)):
    print(name, "median_ms", round(statistics.median(v) * 1000), "max_ms", round(max(v) * 1000))
