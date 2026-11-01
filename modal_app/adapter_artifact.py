"""Versioned, content-addressed LoRA adapter artifact: the contract between the trainer, the Modal inference server,
the checkpoint catalog and the evaluation harness.

Leaf module on purpose (pydantic + stdlib only, no `modal`, no torch, no repo imports) so the trainer container and the
inference container can both verify an artifact without pulling in the rest of the codebase.

An artifact is only ever *final*: an incomplete run has checkpoints (training.resume) but no ArtifactManifest. The
manifest hash covers every other field, and the adapter hash covers every adapter file, so a tampered or truncated
adapter, or a manifest edited after the fact, fails verification before any inference happens."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ARTIFACT_VERSION = "crucible-adapter-v1"
MANIFEST_FILENAME = "artifact_manifest.json"
ADAPTER_CONFIG = "adapter_config.json"
ADAPTER_WEIGHTS = "adapter_model.safetensors"  # safetensors only: pickle-based formats are never accepted
RUN_ID_PATTERN = r"^[a-z0-9][a-z0-9-]{2,62}$"
HEX64 = r"^[0-9a-f]{64}$"
HEX40 = r"^[0-9a-f]{40}$"
_PICKLE_SUFFIXES = (".bin", ".pt", ".pth", ".pkl", ".pickle", ".ckpt")


class ArtifactError(ValueError):
    """A structured, secret-free artifact failure. `code` is stable for tests and operators."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AdapterFile(_Frozen):
    path: str = Field(min_length=1, max_length=200)
    sha256: str = Field(pattern=HEX64)
    size_bytes: int = Field(ge=0)

    @model_validator(mode="after")
    def _safe_relative_path(self) -> "AdapterFile":
        parts = PurePosixPath(self.path).parts
        if not parts or PurePosixPath(self.path).is_absolute() or ".." in parts or "\\" in self.path:
            raise ValueError("adapter file path must be a plain relative posix path")
        if self.path.lower().endswith(_PICKLE_SUFFIXES):
            raise ValueError("pickle-based files are not allowed in an adapter artifact")
        return self


def adapter_content_hash(files: tuple[AdapterFile, ...] | list[AdapterFile]) -> str:
    """Hash of the adapter *content*: independent of file mtimes, directory layout on the volume, or listing order."""
    rows = sorted([f.path, f.sha256, f.size_bytes] for f in files)
    return sha256_hex(canonical_bytes(rows))


def hash_adapter_dir(directory: Path) -> tuple[AdapterFile, ...]:
    """Hash every adapter file under `directory` (the manifest that describes them is not part of the adapter)."""
    root = directory.resolve()
    files = []
    for path in sorted(p for p in root.rglob("*") if p.is_file() and p.name != MANIFEST_FILENAME):
        if path.is_symlink():
            raise ArtifactError("symlink_in_adapter", path.name)
        files.append(AdapterFile(path=path.relative_to(root).as_posix(), sha256=sha256_file(path),
                                 size_bytes=path.stat().st_size))
    return tuple(files)


class LineageEntry(_Frozen):
    """One durable training checkpoint that contributed to this adapter."""
    step: int = Field(ge=1)
    epoch: int = Field(ge=0)
    state_sha256: str = Field(pattern=HEX64)  # hash of that checkpoint's trainer-state metadata


class Segment(_Frozen):
    """One uninterrupted stretch of training on one container: resume produces a new segment."""
    start_step: int = Field(ge=0)
    end_step: int = Field(ge=0)
    duration_seconds: float = Field(ge=0)


class ArtifactManifest(_Frozen):
    artifact_version: Literal["crucible-adapter-v1"] = ARTIFACT_VERSION
    status: Literal["final"] = "final"
    run_id: str = Field(pattern=RUN_ID_PATTERN)
    checkpoint_id: str = Field(pattern=r"^qwen-lora-[0-9a-f]{12}$")
    base_model: str = Field(min_length=1)
    base_revision: str = Field(pattern=HEX40)
    adapter_path: str  # relative to the adapters root: "<run_id>/final"
    adapter_files: tuple[AdapterFile, ...] = Field(min_length=2)
    adapter_hash: str = Field(pattern=HEX64)
    training_manifest_hash: str = Field(pattern=HEX64)
    dataset_hash: str = Field(pattern=HEX64)
    data_source_model_version: str = Field(min_length=1)  # e.g. "scripted-v1": traces from an oracle policy, not a model
    dataset_record_count: int = Field(gt=0)
    plan_hash: str = Field(pattern=HEX64)
    hyperparameters: dict[str, object]
    total_steps: int = Field(gt=0)
    steps_completed: int = Field(gt=0)
    epochs_completed: int = Field(gt=0)
    checkpoint_lineage: tuple[LineageEntry, ...]
    segments: tuple[Segment, ...] = Field(min_length=1)
    duration_seconds: float = Field(ge=0)  # measured: sum of segment wall clock, never an estimate
    gpu: str = Field(min_length=1)
    cost_usd: str | None = None  # None = unknown; never silently 0
    cost_basis: str | None = None
    created_at: dt.datetime
    manifest_hash: str = Field(pattern=HEX64)

    @model_validator(mode="after")
    def _internally_consistent(self) -> "ArtifactManifest":
        if self.steps_completed != self.total_steps:
            raise ValueError("an incomplete run cannot be a final artifact")
        names = {f.path for f in self.adapter_files}
        if not {ADAPTER_CONFIG, ADAPTER_WEIGHTS} <= names:
            raise ValueError(f"adapter artifact must contain {ADAPTER_CONFIG} and {ADAPTER_WEIGHTS}")
        if self.adapter_hash != adapter_content_hash(self.adapter_files):
            raise ValueError("adapter_hash does not match adapter_files")
        if self.checkpoint_id != f"qwen-lora-{self.adapter_hash[:12]}":
            raise ValueError("checkpoint_id is not derived from adapter_hash")
        if self.adapter_path != f"{self.run_id}/final":
            raise ValueError("adapter_path must be <run_id>/final")
        if self.segments[-1].end_step != self.total_steps or self.segments[0].start_step != 0:
            raise ValueError("segments must cover steps 0..total_steps")
        if any(a.end_step != b.start_step for a, b in zip(self.segments, self.segments[1:])):
            raise ValueError("segments must be contiguous")
        if abs(sum(s.duration_seconds for s in self.segments) - self.duration_seconds) > 1e-6:
            raise ValueError("duration_seconds must equal the sum of segment durations")
        if (self.cost_usd is None) != (self.cost_basis is None):
            raise ValueError("cost_usd and cost_basis must both be present or both be unknown")
        if self.created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
        if self.manifest_hash != compute_manifest_hash(self):
            raise ValueError("manifest_hash does not match manifest content")
        return self

    @property
    def selection(self) -> "AdapterSelection":
        return AdapterSelection(run_id=self.run_id, adapter_hash=self.adapter_hash,
                                training_manifest_hash=self.training_manifest_hash)


def compute_manifest_hash(manifest: ArtifactManifest | dict) -> str:
    body = manifest.model_dump(mode="json") if isinstance(manifest, ArtifactManifest) else dict(manifest)
    body.pop("manifest_hash", None)
    return sha256_hex(canonical_bytes(body))


def seal_manifest(**fields: object) -> ArtifactManifest:
    """Build a manifest, deriving adapter_hash / checkpoint_id / adapter_path / duration / manifest_hash itself so a
    caller cannot supply an inconsistent one."""
    files = tuple(fields["adapter_files"])  # type: ignore[arg-type]
    segments = tuple(fields["segments"])  # type: ignore[arg-type]
    adapter_hash = adapter_content_hash(files)
    body = {**fields, "adapter_hash": adapter_hash, "checkpoint_id": f"qwen-lora-{adapter_hash[:12]}",
            "adapter_path": f"{fields['run_id']}/final",
            "duration_seconds": round(sum(s.duration_seconds for s in segments), 6)}
    draft = ArtifactManifest.model_construct(**body, manifest_hash="0" * 64).model_dump(mode="json")
    return ArtifactManifest.model_validate({**draft, "manifest_hash": compute_manifest_hash(draft)})


def load_manifest(path: Path) -> ArtifactManifest:
    try:
        return ArtifactManifest.model_validate_json(path.read_bytes())
    except Exception as exc:  # pydantic/JSON errors can echo field values: keep only the class
        raise ArtifactError("invalid_manifest", type(exc).__name__) from None


def write_manifest(manifest: ArtifactManifest, path: Path) -> None:
    path.write_text(json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n")


class AdapterSelection(_Frozen):
    """What a client asks the inference server to serve. Identity only: the server resolves paths itself, so a request
    can never name an arbitrary file on the volume."""
    run_id: str = Field(pattern=RUN_ID_PATTERN)
    adapter_hash: str = Field(pattern=HEX64)
    training_manifest_hash: str = Field(pattern=HEX64)

    @property
    def checkpoint_id(self) -> str:
        return f"qwen-lora-{self.adapter_hash[:12]}"


def verify_selection(manifest: ArtifactManifest, selection: AdapterSelection, *, base_model: str,
                     base_revision: str) -> None:
    """Reject BEFORE inference: wrong base, wrong adapter content, or an adapter trained on different data."""
    if (manifest.base_model, manifest.base_revision) != (base_model, base_revision):
        raise ArtifactError("base_model_mismatch", "adapter was trained on a different base model or revision")
    if manifest.run_id != selection.run_id:
        raise ArtifactError("run_id_mismatch", "manifest belongs to a different run")
    if manifest.adapter_hash != selection.adapter_hash:
        raise ArtifactError("adapter_hash_mismatch", "adapter content differs from the requested hash")
    if manifest.training_manifest_hash != selection.training_manifest_hash:
        raise ArtifactError("training_manifest_mismatch", "adapter was trained on different data than requested")


def verify_adapter_dir(manifest: ArtifactManifest, directory: Path) -> None:
    """Recompute every file hash on disk; missing, extra, resized or altered files fail closed."""
    if not directory.is_dir():
        raise ArtifactError("adapter_missing", "adapter directory does not exist")
    actual = {f.path: f for f in hash_adapter_dir(directory)}
    expected = {f.path: f for f in manifest.adapter_files}
    if set(actual) != set(expected):
        raise ArtifactError("adapter_files_mismatch", "adapter directory does not match the manifest file list")
    for name, want in expected.items():
        if actual[name] != want:
            raise ArtifactError("adapter_content_mismatch", f"{name} differs from the manifest")
