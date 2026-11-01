"""Live PayPal sandbox checks (create + read + pre-approval rejection only; nothing is paid, no buyer is involved).
Excluded by default; run: `PAYPAL_CLIENT_ID=... PAYPAL_CLIENT_SECRET=... PAYPAL_ENV=sandbox pytest -m live tests/test_payments_live.py`.
The approve/capture/duplicate-capture flow is `scripts/paypal_live_check.py` (explicit confirmation + Kernel authorization)."""
import os
import uuid
from decimal import Decimal

import pytest

from payments.sandbox import SandboxPayments


def live_ready(env=os.environ) -> bool:
    return bool(env.get("PAYPAL_CLIENT_ID") and env.get("PAYPAL_CLIENT_SECRET") and env.get("PAYPAL_ENV") == "sandbox")


pytestmark = [pytest.mark.live, pytest.mark.skipif(not live_ready(), reason="no sandbox credentials / PAYPAL_ENV != sandbox")]


def test_create_is_idempotent_and_exact_amount():
    sb = SandboxPayments()
    key = uuid.uuid4().hex
    a = sb.create_order(Decimal("1.00"), "USD", key)
    assert sb.create_order(Decimal("1.00"), "USD", key) == a  # PayPal-Request-Id replay returns same order
    assert sb.get_status(a) in {"CREATED", "PAYER_ACTION_REQUIRED"}


def test_approval_link_is_on_the_sandbox_host_and_creation_is_not_approval():
    from payments.kernel_approver import check_approval_url
    sb = SandboxPayments()
    oid = sb.create_order(Decimal("1.00"), "USD", uuid.uuid4().hex)
    check_approval_url(sb.approval_url(oid))
    assert sb.get_status(oid) != "APPROVED"


def test_capture_before_approval_is_rejected_and_nothing_is_captured():
    from payments.errors import OrderNotApproved
    sb = SandboxPayments()
    oid = sb.create_order(Decimal("1.00"), "USD", uuid.uuid4().hex)
    with pytest.raises(OrderNotApproved):
        sb.capture(oid)
    assert sb.order_captures(oid) == []

