"""Explicit checkpoint selection: how a genome's `model_checkpoint` label maps to the base model or to ONE verified
trained adapter, with no global default and no environment magic.

  catalog = CheckpointCatalog.from_manifest_files([Path(".../final/artifact_manifest.json")])
  adapter_for = catalog.adapter_for(make_client)            # make_client(AdapterSelection | None) -> QwenInferenceClient
  policy_factory = world.runtime.model_policy_factory(adapter_for, generation_id=...)
  population = build_population(size, seed, fixtures=False, checkpoint=manifest.checkpoint_id)

Labels: "qwen-base" -> pinned base model; "qwen-lora-<12 hex>" -> the registered adapter; anything else (including
"scripted-*") is refused so a scripted policy can never be mistaken for, or silently replaced by, a model."""
from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from pathlib import Path

from modal_app.adapter_artifact import (HEX64, RUN_ID_PATTERN, AdapterSelection, ArtifactError, ArtifactManifest,
                                        load_manifest, verify_selection)
from modal_app.qwen_toolcalls import MODEL_ID, MODEL_REVISION

BASE_LABEL = "qwen-base"
ADAPTER_VOLUME = "crucible-qwen-adapters"
_REF = re.compile(rf"^modal-volume://{ADAPTER_VOLUME}/runs/({RUN_ID_PATTERN[1:-1]})/final@({HEX64[1:-1]})$")


class CheckpointError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code


def artifact_ref(manifest: ArtifactManifest) -> str:
    """Stable, content-addressed reference to a trained adapter (what eval/publish.checkpoint_doc stores as
    `artifact_ref`). The `@<adapter_hash>` suffix makes the reference immutable: same string, same bytes."""
    return f"modal-volume://{ADAPTER_VOLUME}/runs/{manifest.run_id}/final@{manifest.adapter_hash}"


def selection_from_ref(ref: str, *, training_manifest_hash: str) -> AdapterSelection:
    match = _REF.match(ref)
    if not match:
        raise CheckpointError("bad_artifact_ref", "not a crucible adapter artifact reference")
    return AdapterSelection(run_id=match.group(1), adapter_hash=match.group(2), training_manifest_hash=training_manifest_hash)


class CheckpointCatalog:
    def __init__(self, manifests: Iterable[ArtifactManifest] = ()):
        self._by_label: dict[str, ArtifactManifest] = {}
        for manifest in manifests:
            if (manifest.base_model, manifest.base_revision) != (MODEL_ID, MODEL_REVISION):
                raise CheckpointError("incompatible_base", f"{manifest.checkpoint_id} was trained on a different base model/revision")
            known = self._by_label.get(manifest.checkpoint_id)
            if known is not None and known != manifest:
                raise CheckpointError("conflicting_manifest", f"two different manifests claim {manifest.checkpoint_id}")
            self._by_label[manifest.checkpoint_id] = manifest

    @classmethod
    def from_manifest_files(cls, paths: Iterable[Path]) -> "CheckpointCatalog":
        try:
            return cls(load_manifest(Path(p)) for p in paths)
        except ArtifactError as exc:
            raise CheckpointError(exc.code, "an adapter manifest failed verification") from None

    def labels(self) -> tuple[str, ...]:
        return (BASE_LABEL, *sorted(self._by_label))

    def manifest(self, label: str) -> ArtifactManifest:
        try:
            return self._by_label[label]
        except KeyError:
            raise CheckpointError("unknown_checkpoint", f"{label!r} is not registered") from None

    def selection_for(self, label: str, *, expected_training_manifest_hash: str | None = None) -> AdapterSelection | None:
        """None = the base model. An unregistered or scripted label raises: never a quiet base-model substitute."""
        if label == BASE_LABEL:
            return None
        if not label.startswith("qwen-lora-"):
            raise CheckpointError("not_a_model_checkpoint", f"{label!r} does not name a Qwen checkpoint")
        manifest = self.manifest(label)
        selection = manifest.selection
        if expected_training_manifest_hash is not None:
            try:
                verify_selection(manifest, selection.model_copy(update={"training_manifest_hash": expected_training_manifest_hash}),
                                 base_model=MODEL_ID, base_revision=MODEL_REVISION)
            except ArtifactError as exc:
                raise CheckpointError(exc.code, "adapter was trained on a different training manifest") from None
        return selection

    def adapter_for(self, make_client: Callable[[AdapterSelection | None], object], *, max_retries: int = 1,
                    expected_training_manifest_hash: str | None = None) -> Callable[[object], object]:
        """`genome -> ModelAdapter` for world.runtime.model_policy_factory. One client per label, created on first use,
        so each trained checkpoint talks to the server pinned to its own identity."""
        from agents.model import QwenModelAdapter
        cache: dict[str, object] = {}

        def adapter_for(genome) -> object:
            label = genome.model_checkpoint
            if label not in cache:
                selection = self.selection_for(label, expected_training_manifest_hash=expected_training_manifest_hash)
                cache[label] = QwenModelAdapter(make_client(selection), max_retries=max_retries)
            return cache[label]
        return adapter_for
