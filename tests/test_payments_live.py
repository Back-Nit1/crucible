"""Live PayPal sandbox checks. Excluded by default; run: `PAYPAL_CLIENT_ID=... pytest -m live tests/test_payments_live.py`."""
import os
import uuid
from decimal import Decimal

import pytest

from payments.sandbox import SandboxPayments

pytestmark = [pytest.mark.live, pytest.mark.skipif(not os.environ.get("PAYPAL_CLIENT_ID"), reason="no sandbox credentials")]


def test_create_is_idempotent_and_exact_amount():
    sb = SandboxPayments()
    key = uuid.uuid4().hex
    a = sb.create_order(Decimal("1.00"), "USD", key)
    assert sb.create_order(Decimal("1.00"), "USD", key) == a  # PayPal-Request-Id replay returns same order
    assert sb.get_status(a) in {"CREATED", "PAYER_ACTION_REQUIRED"}


def test_capture_before_approval_is_rejected():
    from payments.errors import OrderNotApproved
    sb = SandboxPayments()
    oid = sb.create_order(Decimal("1.00"), "USD", uuid.uuid4().hex)
    with pytest.raises(OrderNotApproved):
        sb.capture(oid)
