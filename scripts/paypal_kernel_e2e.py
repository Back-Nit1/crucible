"""Day-1 checks 1+3: create -> Kernel buyer approval -> capture, with latency. Sandbox only.
usage: paypal_kernel_e2e.py MAIN_ENV BUYER_ENV N   (BUYER_ENV holds PAYPAL_SANDBOX_BUYER_EMAIL/PASSWORD)
Prints sanitized fields only; stops at the first blocked approval."""
import os, sys, time, uuid
sys.path.insert(0, "scripts")
from decimal import Decimal
from _env import load
load(sys.argv[1], {"PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "PAYPAL_ENV", "KERNEL_API_KEY"})
load(sys.argv[2], {"PAYPAL_SANDBOX_BUYER_EMAIL", "PAYPAL_SANDBOX_BUYER_PASSWORD"})
from payments.kernel_approver import ApprovalBlocked, KernelApprover
from payments.sandbox import SandboxPayments

sb = SandboxPayments()
ap = KernelApprover(sb, os.environ["PAYPAL_SANDBOX_BUYER_EMAIL"], os.environ["PAYPAL_SANDBOX_BUYER_PASSWORD"])
for i in range(int(sys.argv[3])):
    t0 = time.perf_counter()
    oid = sb.create_order(Decimal("1.00"), "USD", uuid.uuid4().hex)
    t1 = time.perf_counter()
    print(i, "created", sb.get_status(oid), "create_ms", round((t1 - t0) * 1000))
    try:
        ap.approve(oid)
    except ApprovalBlocked as e:
        print(i, "BLOCKED", e, "- stopping"); sys.exit(2)
    t2 = time.perf_counter()
    cap = sb.capture(oid)
    t3 = time.perf_counter()
    print(i, "approve_ms", round((t2 - t1) * 1000), {k: round(v * 1000) for k, v in ap.timings.items()},
          "capture_ms", round((t3 - t2) * 1000), "capture", cap.status, cap.amount, cap.currency,
          "final_status", sb.get_status(oid), "order", oid)
