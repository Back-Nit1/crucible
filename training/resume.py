"""Durable, atomic, verifiable training checkpoints and the run ledger. Pure stdlib + pydantic (no torch).

A run lives in `<root>/<run_id>/`:

  identity.json          immutable: what this run IS (plan, base model+revision, data hashes, hyperparameters,
                         library signature). A second launch with a different identity is refused, never "resumed".
  ledger.json            launches (budgeted, measured), checkpoint lineage, corrupt checkpoints skipped.
  checkpoints/step-N/    adapter weights + optimizer + scheduler + RNG state (written by the backend) and meta.json
                         holding step / epoch / data position / loss history and the SHA-256 of every file.
  final/                 the finished adapter + artifact_manifest.json (written once, only after the last step).

A checkpoint is written to a temp directory, every file fsynced, meta.json (with all file hashes) written last, then
the directory is renamed into place in one atomic step. A crash can therefore leave a stray temp directory, never a
half-written `step-N`. On resume the newest checkpoint whose files still hash correctly is used; a corrupt one is
skipped and recorded, an incompatible one aborts, and if checkpoints exist but none verify the run refuses to restart
from scratch."""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from modal_app.adapter_artifact import HEX40, HEX64, RUN_ID_PATTERN, LineageEntry, canonical_bytes, sha256_file, sha256_hex

STATE_FORMAT = "crucible-train-state-v1"
META_NAME = "meta.json"
_STEP_DIR = re.compile(r"^step-(\d{6})$")


class ResumeError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RunIdentity(_Frozen):
    run_id: str = Field(pattern=RUN_ID_PATTERN)
    plan_hash: str = Field(pattern=HEX64)
    base_model: str = Field(min_length=1)
    base_revision: str = Field(pattern=HEX40)
    training_manifest_hash: str = Field(pattern=HEX64)
    dataset_hash: str = Field(pattern=HEX64)
    hyperparameters: dict[str, object]
    backend_signature: str = Field(min_length=1)  # library versions: resuming under different ones is refused

    @property
    def identity_hash(self) -> str:
        return sha256_hex(canonical_bytes(self.model_dump(mode="json")))


class CheckpointMeta(_Frozen):
    format: str = STATE_FORMAT
    run_id: str
    identity_hash: str = Field(pattern=HEX64)
    step: int = Field(ge=1)
    epoch: int = Field(ge=0)
    index_in_epoch: int = Field(ge=0)       # optimizer steps already taken inside `epoch`: the sampler position
    loss_history: tuple[float, ...]         # one entry per completed optimizer step
    files: dict[str, str]                   # relative path -> sha256 for everything else in the checkpoint
    created_at: dt.datetime


class Launch(_Frozen):
    index: int = Field(ge=0)
    started_at: dt.datetime
    budget_seconds: float = Field(gt=0)     # hard wall-clock allowance granted to this launch
    start_step: int = Field(ge=0)
    end_step: int = Field(ge=0)
    duration_seconds: float = Field(ge=0)   # measured up to the last durable progress
    closed: bool = False                    # False for a launch that was killed before it could finish cleanly


class Ledger(_Frozen):
    run_id: str
    status: str = "running"                 # running | paused | final
    launches: tuple[Launch, ...] = ()
    lineage: tuple[LineageEntry, ...] = ()
    skipped_corrupt: tuple[str, ...] = ()

    def consumed_seconds_upper_bound(self, now: dt.datetime) -> float:
        """Closed launches count what was measured. A launch that never closed was killed at an unknown moment: it is
        charged the wall clock since it started, capped at its allowance (it cannot have run longer than that)."""
        return sum(l.duration_seconds if l.closed else
                   max(l.duration_seconds, min(l.budget_seconds, (now - l.started_at).total_seconds()))
                   for l in self.launches)


class CheckpointBackend(Protocol):
    """What the store needs from a trainer backend: write/read ALL resumable state into a directory."""
    def capture(self, directory: Path) -> None: ...
    def restore(self, directory: Path) -> None: ...


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with tmp.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    _fsync_dir(path.parent)


def _fsync_tree(directory: Path) -> None:
    for path in directory.rglob("*"):
        if path.is_file():
            fd = os.open(path, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)


def _hash_tree(directory: Path, *, exclude: str = META_NAME) -> dict[str, str]:
    return {p.relative_to(directory).as_posix(): sha256_file(p)
            for p in sorted(directory.rglob("*")) if p.is_file() and p.name != exclude}


class CheckpointStore:
    def __init__(self, root: Path, identity: RunIdentity, *, clock: Callable[[], dt.datetime] | None = None):
        self.run_dir = root / identity.run_id
        self.identity = identity
        self.clock = clock or (lambda: dt.datetime.now(dt.timezone.utc))

    # ---- identity / ledger -------------------------------------------------------------------------------------
    @property
    def checkpoints_dir(self) -> Path:
        return self.run_dir / "checkpoints"

    @property
    def final_dir(self) -> Path:
        return self.run_dir / "final"

    def init_run(self) -> None:
        """Create the run, or verify this launch is the SAME run. Idempotent for an identical identity."""
        path = self.run_dir / "identity.json"
        if path.exists():
            try:
                stored = RunIdentity.model_validate_json(path.read_bytes())
            except Exception:
                raise ResumeError("corrupt_identity", "identity.json is unreadable") from None
            if stored != self.identity:
                differing = sorted(k for k in RunIdentity.model_fields
                                   if getattr(stored, k) != getattr(self.identity, k))
                raise ResumeError("incompatible_run", "run id exists with different " + ", ".join(differing))
            return
        if self.run_dir.exists() and any(self.run_dir.iterdir()):
            raise ResumeError("incompatible_run", "run directory exists without an identity")
        atomic_write_bytes(path, canonical_bytes(self.identity.model_dump(mode="json")))
        self.write_ledger(Ledger(run_id=self.identity.run_id))

    def read_ledger(self) -> Ledger:
        try:
            return Ledger.model_validate_json((self.run_dir / "ledger.json").read_bytes())
        except Exception:
            raise ResumeError("corrupt_ledger", "ledger.json is missing or unreadable") from None

    def write_ledger(self, ledger: Ledger) -> None:
        atomic_write_bytes(self.run_dir / "ledger.json", canonical_bytes(ledger.model_dump(mode="json")))

    # ---- checkpoints -------------------------------------------------------------------------------------------
    def _candidates(self) -> list[tuple[int, Path]]:
        if not self.checkpoints_dir.is_dir():
            return []
        found = [(int(m.group(1)), p) for p in self.checkpoints_dir.iterdir() if (m := _STEP_DIR.match(p.name)) and p.is_dir()]
        return sorted(found, reverse=True)

    def _verify(self, step: int, directory: Path) -> CheckpointMeta:
        try:
            meta = CheckpointMeta.model_validate_json((directory / META_NAME).read_bytes())
        except Exception:
            raise ResumeError("corrupt_checkpoint", f"{directory.name}: meta.json unreadable") from None
        if meta.format != STATE_FORMAT or meta.run_id != self.identity.run_id or meta.step != step:
            raise ResumeError("corrupt_checkpoint", f"{directory.name}: metadata does not describe this step")
        if meta.identity_hash != self.identity.identity_hash:
            raise ResumeError("incompatible_checkpoint", f"{directory.name} was written by a different run identity")
        if _hash_tree(directory) != meta.files:
            raise ResumeError("corrupt_checkpoint", f"{directory.name}: file hashes do not match meta.json")
        return meta

    def latest_valid(self) -> tuple[CheckpointMeta, Path] | None:
        """Newest verifiable checkpoint, or None for a run that never saved one. Corrupt ones are skipped and
        recorded; incompatible ones abort; checkpoints that exist but all fail verification abort (no silent restart)."""
        candidates = self._candidates()
        skipped: list[str] = []
        for step, directory in candidates:
            try:
                meta = self._verify(step, directory)
            except ResumeError as exc:
                if exc.code != "corrupt_checkpoint":
                    raise
                skipped.append(directory.name)
                continue
            if skipped:
                ledger = self.read_ledger()
                self.write_ledger(ledger.model_copy(update={"skipped_corrupt": ledger.skipped_corrupt + tuple(skipped)}))
            return meta, directory
        if candidates:
            raise ResumeError("no_valid_checkpoint", "checkpoints exist but none verify; refusing to restart from scratch")
        return None

    def save(self, *, step: int, epoch: int, index_in_epoch: int, loss_history: tuple[float, ...],
             backend: CheckpointBackend) -> CheckpointMeta:
        final = self.checkpoints_dir / f"step-{step:06d}"
        if final.exists():
            return self._verify(step, final)  # idempotent: the same step was already durably saved
        tmp = self.checkpoints_dir / f".tmp-{step:06d}-{uuid.uuid4().hex}"
        tmp.mkdir(parents=True)
        try:
            backend.capture(tmp)
            _fsync_tree(tmp)
            meta = CheckpointMeta(run_id=self.identity.run_id, identity_hash=self.identity.identity_hash, step=step,
                                  epoch=epoch, index_in_epoch=index_in_epoch, loss_history=loss_history,
                                  files=_hash_tree(tmp), created_at=self.clock())
            (tmp / META_NAME).write_bytes(canonical_bytes(meta.model_dump(mode="json")))
            _fsync_tree(tmp)
            os.rename(tmp, final)  # atomic publish
            _fsync_dir(self.checkpoints_dir)
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        ledger = self.read_ledger()
        entry = LineageEntry(step=step, epoch=epoch, state_sha256=sha256_file(final / META_NAME))
        self.write_ledger(ledger.model_copy(update={"lineage": ledger.lineage + (entry,)}))
        return meta

    def prune(self, keep: int = 2) -> None:
        """Drop old checkpoint payloads (lineage hashes stay in the ledger) and any temp dirs from a crashed save."""
        if self.checkpoints_dir.is_dir():
            for path in self.checkpoints_dir.glob(".tmp-*"):
                shutil.rmtree(path, ignore_errors=True)
        for _, directory in self._candidates()[keep:]:
            shutil.rmtree(directory, ignore_errors=True)

    # ---- launches ----------------------------------------------------------------------------------------------
    def begin_launch(self, *, budget_seconds: float, start_step: int) -> int:
        """Open a launch. Earlier launches that never closed were hard-killed: close them at the resumed step
        (discarded work stays in their measured duration) so segments stay contiguous."""
        ledger = self.read_ledger()
        launches = []
        for launch in ledger.launches:
            if not launch.closed or launch.end_step > start_step:  # killed, or its newest checkpoint was unusable
                launch = launch.model_copy(update={"closed": True, "end_step": min(launch.end_step, start_step)})
            launches.append(launch)
        index = len(launches)
        launches.append(Launch(index=index, started_at=self.clock(), budget_seconds=budget_seconds, start_step=start_step,
                               end_step=start_step, duration_seconds=0))
        self.write_ledger(ledger.model_copy(update={"launches": tuple(launches), "status": "running"}))
        return index

    def record_progress(self, index: int, *, end_step: int, duration_seconds: float, close: bool = False,
                        status: str | None = None) -> None:
        ledger = self.read_ledger()
        launches = tuple(l.model_copy(update={"end_step": end_step, "duration_seconds": duration_seconds,
                                              "closed": close or l.closed}) if l.index == index else l
                         for l in ledger.launches)
        update: dict[str, object] = {"launches": launches}
        if status:
            update["status"] = status
        self.write_ledger(ledger.model_copy(update=update))
