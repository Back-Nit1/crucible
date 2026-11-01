"""Sanitized payment ledger: what actually happened to an order, safe to show a UI or commit as evidence.

Stores only: backend mode, event kind, time, amount/currency, PayPal order/capture ids (not secrets), a hash of the
idempotency key, the idempotency outcome, latency and a failure *code*. Never credentials, tokens, approval URLs,
response bodies, debug ids or payer identity. The PayPal sandbox ledger stays the source of truth for real captures;
this is our own record of the calls we made."""
import datetime as dt
import hashlib
import threading
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

Event = Literal["proposal", "confirmation", "approval", "capture", "failure"]


class LedgerEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    seq: int
    at: dt.datetime
    mode: Literal["mock", "sandbox"]
    event: Event
    amount: Decimal | None = None
    currency: str | None = None
    order_ref: str | None = None
    capture_ref: str | None = None
    status: str | None = None  # PayPal order/capture status as observed
    idempotency_key_hash: str | None = None
    idempotency_outcome: Literal["created", "replayed"] | None = None
    latency_ms: int | None = None
    failure_code: str | None = None
    run_id: str | None = None
    generation_id: str | None = None


def key_hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:16]


class PaymentLedger:
    def __init__(self, mode: Literal["mock", "sandbox"], clock=lambda: dt.datetime.now(dt.UTC),
                 generation_id: str | None = None):
        self.mode, self.clock, self.generation_id = mode, clock, generation_id
        self._rows: list[LedgerEntry] = []
        self._lock = threading.Lock()

    def record(self, event: Event, *, idempotency_key: str | None = None, **fields) -> LedgerEntry:
        with self._lock:
            row = LedgerEntry(seq=len(self._rows), at=self.clock(), mode=self.mode, event=event,
                              idempotency_key_hash=key_hash(idempotency_key) if idempotency_key else None,
                              generation_id=self.generation_id, **fields)
            self._rows.append(row)
            return row

    def entries(self, run_id: str | None = None) -> list[LedgerEntry]:
        with self._lock:
            return [r for r in self._rows if run_id is None or r.run_id == run_id]

    def captures(self) -> list[LedgerEntry]:
        """Charges actually made by this process: replays are not charges."""
        return [r for r in self.entries() if r.event == "capture" and r.idempotency_outcome == "created"]
