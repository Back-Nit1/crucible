"""Atomic, versioned, self-verifying persistence for generation state (Phase 5).

One JSON blob per generation: {"version", "content_hash", "body"}; `content_hash` is the sha256 of the canonical body.
Writes go to a temp object and are atomically swapped in (os.replace on a filesystem / a Modal Volume mount),
so a crash leaves either the previous committed state or the new one - never a torn file. Resume schedules only
`remaining_episode_keys()` and refuses a store written under different task/catalog/rules/population versions."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import tempfile
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Callable, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from world.evolution import GenerationCheckpoint, GenerationSummary, select_survivors

STORE_VERSION = 1


class GenerationStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    INTERRUPTED = "interrupted"
    COMPLETED = "completed"
    FAILED = "failed"


class CorruptCheckpoint(Exception):
    """Unreadable, hash-mismatched or schema-invalid state: never resumed from."""


class IncompatibleCheckpoint(Exception):
    """State was written for a different task set, catalog, kill-rule set or population."""


class GenerationLocked(Exception):
    """Another live runner owns this generation."""


class Compat(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    task_set_hash: str  # hash over task ids + their catalog/manifest hashes + task version
    catalog_hash: str
    rules_version: str  # hash/label of the enabled kill-rule registry (id:version)
    population_hash: str  # hash over genome hashes


class EpisodeOutcome(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    episode_id: str
    fitness: Decimal
    killed: bool
    kill_rules: tuple[str, ...] = ()
    termination: str


class GenerationState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    status: GenerationStatus = GenerationStatus.PENDING
    compat: Compat
    checkpoint: GenerationCheckpoint
    outcomes: dict[str, EpisodeOutcome] = Field(default_factory=dict)  # episode key -> result
    summary: GenerationSummary | None = None
    error: str | None = None  # sanitized failure class + message, never a secret or traceback

    def remaining(self) -> tuple[str, ...]:
        return self.checkpoint.remaining_episode_keys()


def _canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def digest(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


def encode(state: GenerationState) -> bytes:
    body = state.model_dump(mode="json")
    return json.dumps({"version": STORE_VERSION, "content_hash": digest(_canon(body)), "body": body}).encode()


def decode(raw: bytes) -> GenerationState:
    try:
        doc = json.loads(raw)
        if doc["version"] != STORE_VERSION:
            raise CorruptCheckpoint(f"unsupported checkpoint version {doc['version']!r}")
        if digest(_canon(doc["body"])) != doc["content_hash"]:
            raise CorruptCheckpoint("content hash mismatch")
        return GenerationState.model_validate(doc["body"])
    except CorruptCheckpoint:
        raise
    except (ValueError, KeyError, TypeError, ValidationError) as e:
        raise CorruptCheckpoint(f"unreadable checkpoint: {type(e).__name__}") from e


class BlobStore(Protocol):
    def read(self, key: str) -> bytes | None: ...
    def write(self, key: str, data: bytes) -> None: ...  # atomic replace
    def create_exclusive(self, key: str, data: bytes) -> bool: ...  # True if created, False if it already existed
    def delete(self, key: str) -> None: ...


class MemoryBlobStore:
    def __init__(self):
        self.blobs: dict[str, bytes] = {}

    def read(self, key):
        return self.blobs.get(key)

    def write(self, key, data):
        self.blobs[key] = data

    def create_exclusive(self, key, data):
        return self.blobs.setdefault(key, data) is data

    def delete(self, key):
        self.blobs.pop(key, None)


class FileBlobStore:
    """Filesystem store. On a Modal Volume mount pass `after_write=volume.commit` and `before_read=volume.reload`
    (see modal_app); locally both are None."""

    def __init__(self, root: Path | str, after_write: Callable[[], None] | None = None,
                 before_read: Callable[[], None] | None = None):
        self.root, self.after_write, self.before_read = Path(root), after_write, before_read
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        if "/" in key or key.startswith("."):
            raise ValueError(f"bad key {key!r}")
        return self.root / key

    def read(self, key):
        if self.before_read:
            self.before_read()
        p = self._path(key)
        return p.read_bytes() if p.exists() else None

    def write(self, key, data):
        fd, tmp = tempfile.mkstemp(dir=self.root, prefix=".tmp-")  # same directory => same filesystem => atomic replace
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self._path(key))
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        if self.after_write:
            self.after_write()

    def create_exclusive(self, key, data):
        try:
            fd = os.open(self._path(key), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return False
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        if self.after_write:
            self.after_write()
        return True

    def delete(self, key):
        self._path(key).unlink(missing_ok=True)
        if self.after_write:
            self.after_write()


class GenerationStore:
    def __init__(self, blobs: BlobStore):
        self.blobs = blobs

    @staticmethod
    def key(generation_id: str) -> str:
        return f"gen-{generation_id}.json"

    def load(self, generation_id: str) -> GenerationState | None:
        raw = self.blobs.read(self.key(generation_id))
        return None if raw is None else decode(raw)

    def save(self, generation_id: str, state: GenerationState) -> None:
        assert state.checkpoint.generation_id == generation_id
        self.blobs.write(self.key(generation_id), encode(state))

    def start_or_resume(self, generation_id: str, fresh: GenerationState) -> GenerationState:
        """Create the generation, or resume the stored one after verifying it is compatible and intact.
        A completed generation is returned unchanged (idempotent). An unreadable one raises CorruptCheckpoint."""
        stored = self.load(generation_id)
        if stored is None:
            self.save(generation_id, fresh)
            return fresh
        if stored.compat != fresh.compat:
            raise IncompatibleCheckpoint(f"{generation_id}: stored {stored.compat} != requested {fresh.compat}")
        if stored.checkpoint.seed != fresh.checkpoint.seed or stored.checkpoint.genomes != fresh.checkpoint.genomes \
                or stored.checkpoint.task_ids != fresh.checkpoint.task_ids:
            raise IncompatibleCheckpoint(f"{generation_id}: seed, genomes or tasks differ")
        return stored

    def set_status(self, generation_id: str, status: GenerationStatus, error: str | None = None) -> GenerationState:
        state = self.load(generation_id)
        state = state.model_copy(update={"status": status, "error": error})
        self.save(generation_id, state)
        return state

    def record_episode(self, generation_id: str, key: str, outcome: EpisodeOutcome) -> GenerationState:
        """Mark one genome:task pair done. Re-recording a completed key is a no-op, so a replay cannot duplicate it."""
        state = self.load(generation_id)
        if key in state.checkpoint.completed_episode_keys:
            return state
        if key not in state.checkpoint.remaining_episode_keys():
            raise ValueError(f"{key} is not part of generation {generation_id}")
        cp = state.checkpoint.model_copy(update={
            "completed_episode_keys": (*state.checkpoint.completed_episode_keys, key)})
        state = state.model_copy(update={"checkpoint": cp, "outcomes": {**state.outcomes, key: outcome}})
        self.save(generation_id, state)
        return state

    def finalize(self, generation_id: str) -> GenerationState:
        """Deterministic summary once every genome:task pair has an outcome. Fitness per genome is the mean of its
        episode fitness (6 dp); a genome with any killed episode is killed. Idempotent."""
        state = self.load(generation_id)
        if state.remaining():
            raise ValueError(f"{generation_id} still has {len(state.remaining())} episodes to run")
        cp = state.checkpoint
        fitness, killed = {}, []
        for g in cp.genomes:
            outs = [state.outcomes[f"{g.id}:{t}"] for t in cp.task_ids]
            fitness[g.id] = (sum((o.fitness for o in outs), Decimal(0)) / len(outs)).quantize(Decimal("0.000001"))
            if any(o.killed for o in outs):
                killed.append(g.id)
        survivors = select_survivors(cp.genomes, fitness, set(killed))
        values = list(fitness.values())
        summary = GenerationSummary(
            generation_id=generation_id, seed=cp.seed, population_ids=tuple(g.id for g in cp.genomes),
            survivor_ids=tuple(g.id for g in survivors), killed_ids=tuple(sorted(killed)),
            best_fitness=max(values), mean_fitness=(sum(values, Decimal(0)) / len(values)).quantize(Decimal("0.000001")))
        cp = cp.model_copy(update={"fitness": fitness, "killed_agent_ids": tuple(sorted(killed)), "status": "complete"})
        state = state.model_copy(update={"checkpoint": cp, "summary": summary, "status": GenerationStatus.COMPLETED})
        self.save(generation_id, state)
        return state

    # --- single-writer lease (expires, so a preempted runner cannot wedge the generation forever) -------------
    def acquire(self, generation_id: str, owner: str, ttl: dt.timedelta = dt.timedelta(minutes=30),
                now: dt.datetime | None = None) -> None:
        now, key = now or dt.datetime.now(dt.UTC), f"lock-{generation_id}"
        if self.blobs.create_exclusive(key, f"{owner}|{now.isoformat()}".encode()):
            return
        held = (self.blobs.read(key) or b"?|").decode()
        holder, _, since = held.partition("|")
        try:
            stale = now - dt.datetime.fromisoformat(since) > ttl
        except ValueError:
            stale = True  # unreadable lease: treat as abandoned
        if not stale:
            raise GenerationLocked(f"{generation_id} is owned by {holder}")
        self.blobs.delete(key)  # takeover; if two takers race, only one create_exclusive wins
        if not self.blobs.create_exclusive(key, f"{owner}|{now.isoformat()}".encode()):
            raise GenerationLocked(f"{generation_id} was taken over concurrently")

    def release(self, generation_id: str) -> None:
        self.blobs.delete(f"lock-{generation_id}")
