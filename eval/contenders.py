"""Executable contender configuration. Every identity field is explicit and validated; a placeholder never loads."""
from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Words that mark a value as a stand-in. Matched anywhere, so "qwen-base-placeholder" cannot slip through.
PLACEHOLDER = re.compile(r"placeholder|todo|tbd|changeme|fixme|dummy|lorem|\bfake\b|\bxxx+\b", re.I)
SHA40, SHA64 = re.compile(r"^[0-9a-f]{40}$"), re.compile(r"^[0-9a-f]{64}$")


class ContenderError(ValueError):
    """A contender cannot be executed or reported as configured."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ContenderConfig(_Strict):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    kind: Literal["base", "finetuned", "frontier"]
    model_id: str = Field(min_length=1)
    base_revision: str = Field(min_length=1)       # 40-hex commit for open models; provider version string for frontier
    adapter_ref: str | None = Field(default=None, min_length=1)
    adapter_sha256: str | None = None
    training_manifest_hash: str | None = None
    memory_enabled: bool
    memory_k: int = Field(default=2, ge=1, le=10)
    prompt_version: str = Field(min_length=1)
    system_prompt_variant: str = "grounded-shopper-v1"
    temperature: Decimal = Field(ge=0, le=2)
    endpoint: str = Field(min_length=1)            # e.g. "modal:crucible-qwen-inference/Qwen"
    optional: bool = False
    spend_authorized: bool = False                 # frontier only: explicit user authorization for paid calls

    @model_validator(mode="after")
    def valid_identity(self) -> ContenderConfig:
        for name, value in self.model_dump(mode="json").items():
            if isinstance(value, str) and PLACEHOLDER.search(value):
                raise ContenderError(f"contender {self.id!r}: {name}={value!r} is a placeholder")
        if self.kind != "frontier" and not SHA40.match(self.base_revision):
            raise ContenderError(f"contender {self.id!r}: base_revision must be a 40-hex commit")
        adapter = (self.adapter_ref, self.adapter_sha256, self.training_manifest_hash)
        if self.kind == "finetuned":
            if not all(adapter):
                raise ContenderError(f"contender {self.id!r}: finetuned needs adapter_ref, adapter_sha256 and "
                                     "training_manifest_hash; no fine-tuned artifact means no fine-tuned contender")
            if not (SHA64.match(self.adapter_sha256) and SHA64.match(self.training_manifest_hash)):
                raise ContenderError(f"contender {self.id!r}: adapter and training hashes must be 64-hex sha256")
        elif any(adapter):
            raise ContenderError(f"contender {self.id!r}: only finetuned contenders may carry an adapter")
        if self.kind == "frontier" and not self.spend_authorized:
            raise ContenderError(f"contender {self.id!r}: frontier spend is not authorized")
        return self

    @property
    def checkpoint(self) -> str:
        base = f"{self.model_id}@{self.base_revision}"
        return f"{base}+adapter:{self.adapter_sha256[:12]}" if self.adapter_sha256 else base

    @property
    def request_checkpoint(self) -> str:
        """What every model request pins; a client that cannot serve it must refuse (no silent fallback to base)."""
        return f"qwen-lora-{self.adapter_sha256[:12]}" if self.adapter_sha256 else self.base_revision  # label published by the trainer

    @property
    def identity_hash(self) -> str:
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()


class AdapterReference(_Strict):
    """The public artifact reference a trainer publishes (see coordination/evaluation.md). Nothing here is invented."""
    adapter_ref: str = Field(min_length=1)
    adapter_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    base_model: str = Field(min_length=1)
    base_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    training_manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def from_artifact_manifest(cls, artifact) -> "AdapterReference":
        """Build the evaluator's neutral reference from a sealed trainer artifact or its manifest path."""
        from modal_app.adapter_artifact import ArtifactManifest, load_manifest
        from training.checkpoints import artifact_ref

        manifest = artifact if isinstance(artifact, ArtifactManifest) else load_manifest(Path(artifact))
        return cls(adapter_ref=artifact_ref(manifest), adapter_sha256=manifest.adapter_hash,
                   base_model=manifest.base_model, base_revision=manifest.base_revision,
                   training_manifest_hash=manifest.training_manifest_hash)


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_adapter_reference(path: str | Path) -> AdapterReference:
    """Read the trainer's reference JSON; a missing file means the artifact does not exist yet."""
    p = Path(path)
    if not p.is_file():
        raise ContenderError(f"adapter reference {p} does not exist: the fine-tuned artifact has not been produced")
    ref = AdapterReference.model_validate_json(p.read_text())
    if PLACEHOLDER.search(ref.model_dump_json()):
        raise ContenderError("adapter reference contains a placeholder value")
    local = Path(ref.adapter_ref)
    if local.is_file() and sha256_file(local) != ref.adapter_sha256:
        raise ContenderError("adapter artifact hash does not match the reference")
    return ref


def standard_contenders(*, model_id: str, base_revision: str, prompt_version: str, endpoint: str,
                        temperature: Decimal = Decimal("0"), memory_k: int = 2,
                        adapter: AdapterReference | None = None) -> tuple[ContenderConfig, ...]:
    """Base, base+memory and (only when a real adapter reference is supplied) the fine-tuned survivor."""
    common = dict(model_id=model_id, base_revision=base_revision, prompt_version=prompt_version, endpoint=endpoint,
                  temperature=temperature, memory_k=memory_k)
    out = [ContenderConfig(id="base-qwen", kind="base", memory_enabled=False, **common),
           ContenderConfig(id="base-qwen-memory", kind="base", memory_enabled=True, **common)]
    if adapter is not None:
        if (adapter.base_model, adapter.base_revision) != (model_id, base_revision):
            raise ContenderError("adapter was trained on a different base model or revision")
        out.append(ContenderConfig(id="survivor-finetuned", kind="finetuned", memory_enabled=False,
                                   adapter_ref=adapter.adapter_ref, adapter_sha256=adapter.adapter_sha256,
                                   training_manifest_hash=adapter.training_manifest_hash, **common))
    return tuple(out)
