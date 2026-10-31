"""Payment failures shared by every backend, so mock and sandbox map errors identically."""


class PaymentError(Exception):
    """Gateway rejected or failed a call. `code` is PayPal's `details[0].issue` (else `name`)."""

    def __init__(self, code: str, message: str = "", http_status: int | None = None,
                 debug_id: str | None = None):
        super().__init__(f"{code}: {message}" if message else code)
        self.code, self.http_status, self.debug_id = code, http_status, debug_id


class OrderNotApproved(PaymentError):
    """Capture attempted before the buyer approved (ORDER_NOT_APPROVED / PAYER_ACTION_REQUIRED)."""


class OrderNotFound(PaymentError):
    """RESOURCE_NOT_FOUND / INVALID_RESOURCE_ID."""


class PaymentDeclined(PaymentError):
    """INSTRUMENT_DECLINED / TRANSACTION_REFUSED, or a capture that came back non-COMPLETED."""


class AmountMismatch(PaymentError):
    """Captured amount differs from the amount the order was created with."""
