"""Live training progress for the Observatory.

The trainer (on Modal) writes one small record per run into a Modal Dict; the API reads the Dict and streams it to the
web over server-sent events. Publishing is throttled and best-effort: a slow or failing write never slows or fails a
paid GPU step. Records hold numbers and ids only (no data rows, no model text, no paths).

Reading is off unless CRUCIBLE_LIVE_TRAINING=modal (the API then needs Modal credentials: MODAL_TOKEN_ID/SECRET or
~/.modal.toml). Writing happens inside the Modal training container, which needs no extra credentials."""
from __future__ import annotations

import datetime as dt
import os
import time
from collections import deque
from collections.abc import Callable, MutableMapping

DICT_NAME = "crucible-live-training"
FIELDS = ("run_id", "algorithm", "base_model", "gpu", "status", "step", "total_steps", "resumed_from_step", "loss",
          "losses", "started_at", "updated_at")
Publish = Callable[..., None]


def modal_store() -> MutableMapping:
    import modal
    return modal.Dict.from_name(DICT_NAME, create_if_missing=True)


def publisher(store: MutableMapping | None, *, run_id: str, static: dict, min_interval: float = 2.0,
              monotonic: Callable[[], float] = time.monotonic,
              now: Callable[[], dt.datetime] = lambda: dt.datetime.now(dt.UTC)) -> Publish:
    """`publish(step=, total_steps=, loss=None, status="running")`: at most one write per `min_interval` seconds,
    except status changes, which always write. Keeps the last 60 step losses for the sparkline."""
    losses: deque[float] = deque(maxlen=60)
    last = {"t": float("-inf"), "status": None}
    started = now().isoformat()

    def publish(*, step: int, total_steps: int, loss: float | None = None, status: str = "running") -> None:
        if loss is not None:
            losses.append(round(float(loss), 6))
        t = monotonic()
        if store is None or (status == last["status"] and t - last["t"] < min_interval):
            return
        last.update(t=t, status=status)
        record = {**static, "run_id": run_id, "status": status, "step": step, "total_steps": total_steps,
                  "loss": losses[-1] if losses else None, "losses": list(losses), "started_at": started,
                  "updated_at": now().isoformat()}
        try:
            store[run_id] = {k: record.get(k) for k in FIELDS}
        except Exception:  # noqa: BLE001 - progress display must never break training
            pass
    return publish


def read_runs(store: MutableMapping, limit: int = 10) -> list[dict]:
    """Newest-first whitelisted records."""
    rows = [{k: v.get(k) for k in FIELDS} for _, v in store.items() if isinstance(v, dict)]
    return sorted(rows, key=lambda r: str(r.get("updated_at") or ""), reverse=True)[:limit]


def source_from_env(ttl: float = 2.0) -> Callable[[], list[dict]]:
    """Cached reader for the API; returns [] when disabled or when Modal is unreachable."""
    if os.environ.get("CRUCIBLE_LIVE_TRAINING") != "modal":
        return lambda: []
    cache: dict = {"t": float("-inf"), "rows": [], "store": None}

    def read() -> list[dict]:
        if time.monotonic() - cache["t"] < ttl:
            return cache["rows"]
        try:
            cache["store"] = cache["store"] or modal_store()
            cache["rows"] = read_runs(cache["store"])
        except Exception:  # noqa: BLE001 - Modal down or not configured: show nothing rather than fail the page
            cache["rows"] = []
        cache["t"] = time.monotonic()
        return cache["rows"]
    return read
