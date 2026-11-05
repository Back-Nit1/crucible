"""Pure, Modal-free logic behind the world scheduler (testable offline): idempotent run, resume-latest, status, cost."""
from __future__ import annotations

import time

from world.store import GenerationState, GenerationStatus, GenerationStore

CPU_CORES, MEMORY_GIB = 1.0, 1.0  # must match the Modal function's cpu / memory below
CPU_RATE_USD_PER_CORE_SECOND = 0.0000131  # verified in modal_app/qwen_toolcalls.py (Modal list price)
MEMORY_RATE_USD_PER_GIB_SECOND = 0.00000222
UNFINISHED = {GenerationStatus.PENDING, GenerationStatus.RUNNING, GenerationStatus.INTERRUPTED}


def approx_cost_usd(seconds: float, gpu_rate_per_second: float = 0.0) -> dict:
    cpu = seconds * CPU_CORES * CPU_RATE_USD_PER_CORE_SECOND
    mem = seconds * MEMORY_GIB * MEMORY_RATE_USD_PER_GIB_SECOND
    gpu = seconds * gpu_rate_per_second
    return {"seconds": round(seconds, 2), "cpu_usd": round(cpu, 6), "memory_usd": round(mem, 6), "gpu_usd": round(gpu, 6),
            "total_usd": round(cpu + mem + gpu, 6), "basis": "wall time x Modal list price; approximate, excludes Elastic"}


def brief(gid: str, st: GenerationState | None) -> dict:
    if st is None:
        return {"generation_id": gid, "status": "corrupt"}
    done, total = len(st.checkpoint.completed_episode_keys), len(st.checkpoint.episode_keys())
    return {"generation_id": gid, "status": st.status.value, "episodes": f"{done}/{total}", "error": st.error,
            "survivors": list(st.summary.survivor_ids) if st.summary else None}


def status(store: GenerationStore) -> list[dict]:
    return [brief(g, s) for g, s in store.generations()]


def latest_unfinished(store: GenerationStore) -> str | None:
    """Most recent resumable generation (the scheduler resumes; it never starts a new one on its own)."""
    open_ids = [g for g, s in store.generations() if s is not None and s.status in UNFINISHED]
    return open_ids[-1] if open_ids else None


def timed(fn, *a, **kw):
    t0 = time.monotonic()
    out = fn(*a, **kw)
    return out, time.monotonic() - t0
