"""Atomic, resumable storage for `world.evolution.GenerationCheckpoint` (spec 8.5, 14: resumable generations).

One JSON file per generation: {"sha256", "checkpoint", "results"}. Writes go to a temp file in the same directory,
are fsynced, then `os.replace`d, so a crash leaves either the old or the new file and never a torn one. A cross-process
lock serialises read-modify-write. `complete()` is idempotent: a finished genome/task pair is never recorded twice, and
`remaining()` returns exactly `GenerationCheckpoint.remaining_episode_keys()`. On Modal, pass `commit=volume.commit`."""
import contextlib
import fcntl
import hashlib
import json
import os
import re
import tempfile
from collections.abc import Callable
from pathlib import Path

from world.evolution import GenerationCheckpoint


class CheckpointCorrupt(RuntimeError): ...
class CheckpointConflict(RuntimeError): ...


def _digest(checkpoint: dict, results: dict) -> str:
    return hashlib.sha256(json.dumps([checkpoint, results], sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class CheckpointStore:
    def __init__(self, root: str | Path, commit: Callable[[], None] | None = None):
        self.root, self.commit = Path(root), commit
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, generation_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", generation_id):
            raise ValueError(f"unsafe generation id {generation_id!r}")
        return self.root / f"{generation_id}.json"

    @contextlib.contextmanager
    def _lock(self, generation_id: str):
        with open(self.root / f".{generation_id}.lock", "w") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)

    def _read(self, generation_id: str) -> tuple[GenerationCheckpoint, dict] | None:
        path = self._path(generation_id)
        if not path.exists():
            return None
        try:
            doc = json.loads(path.read_text())
            if doc["sha256"] != _digest(doc["checkpoint"], doc["results"]):
                raise CheckpointCorrupt(f"{path.name}: checksum mismatch")
            return GenerationCheckpoint.model_validate(doc["checkpoint"]), doc["results"]
        except (ValueError, KeyError) as e:  # JSON/validation errors: never resume from a damaged file
            raise CheckpointCorrupt(f"{path.name}: {type(e).__name__}") from e

    def _write(self, cp: GenerationCheckpoint, results: dict) -> None:
        payload = cp.model_dump(mode="json")
        doc = {"sha256": _digest(payload, results), "checkpoint": payload, "results": results}
        fd, tmp = tempfile.mkstemp(dir=self.root, prefix=f".{cp.generation_id}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as fh:
                json.dump(doc, fh, sort_keys=True)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self._path(cp.generation_id))
        except BaseException:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(tmp)
            raise
        dfd = os.open(self.root, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
        if self.commit:
            self.commit()

    def load(self, generation_id: str) -> GenerationCheckpoint | None:
        got = self._read(generation_id)
        return got[0] if got else None

    def results(self, generation_id: str) -> dict[str, dict]:
        got = self._read(generation_id)
        return got[1] if got else {}

    def create(self, cp: GenerationCheckpoint) -> GenerationCheckpoint:
        """Idempotent: re-creating an identical run returns the stored state; a different run under the same id is refused."""
        with self._lock(cp.generation_id):
            got = self._read(cp.generation_id)
            if got is None:
                self._write(cp, {})
                return cp
            stored = got[0]
            same = (stored.seed, stored.genomes, stored.task_ids) == (cp.seed, cp.genomes, cp.task_ids)
            if not same:
                raise CheckpointConflict(f"generation {cp.generation_id} already exists with different genomes/tasks/seed")
            return stored

    def remaining(self, generation_id: str) -> tuple[str, ...]:
        cp = self.load(generation_id)
        if cp is None:
            raise KeyError(generation_id)
        return cp.remaining_episode_keys()

    def complete(self, generation_id: str, episode_key: str, result: dict) -> GenerationCheckpoint:
        """Record one finished genome/task pair with its result. Recording an already-finished pair changes nothing."""
        with self._lock(generation_id):
            got = self._read(generation_id)
            if got is None:
                raise KeyError(generation_id)
            cp, results = got
            if episode_key in cp.completed_episode_keys:
                return cp
            if episode_key not in cp.remaining_episode_keys():
                raise ValueError(f"{episode_key!r} is not a genome/task pair of generation {generation_id}")
            cp = cp.model_copy(update={"completed_episode_keys": (*cp.completed_episode_keys, episode_key)})
            self._write(cp, {**results, episode_key: result})
            return cp

    def finalize(self, generation_id: str, fitness: dict, killed_agent_ids: tuple[str, ...]) -> GenerationCheckpoint:
        """Mark the generation complete; only allowed once every genome/task pair has been recorded."""
        with self._lock(generation_id):
            cp, results = self._read(generation_id) or (None, None)
            if cp is None:
                raise KeyError(generation_id)
            if cp.remaining_episode_keys():
                raise ValueError(f"{len(cp.remaining_episode_keys())} episodes still remaining")
            cp = cp.model_copy(update={"fitness": fitness, "killed_agent_ids": killed_agent_ids, "status": "complete"})
            GenerationCheckpoint.model_validate(cp.model_dump())  # re-run the cross-field validators
            self._write(cp, results)
            return cp
