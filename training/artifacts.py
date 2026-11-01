"""Finalize a completed run into the versioned adapter artifact (re-exports the leaf contract in
modal_app.adapter_artifact so callers have one import for everything artifact-shaped)."""
from __future__ import annotations

import datetime as dt
import os
import shutil
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Callable

from modal_app.adapter_artifact import (  # noqa: F401  (re-exported public surface)
    ADAPTER_CONFIG, ADAPTER_WEIGHTS, ARTIFACT_VERSION, MANIFEST_FILENAME, AdapterFile, AdapterSelection, ArtifactError,
    ArtifactManifest, LineageEntry, Segment, hash_adapter_dir, load_manifest, seal_manifest, verify_adapter_dir,
    verify_selection, write_manifest)
from training.planning import LoRAHyperparameters, ResourceRates
from training.resume import CheckpointStore, RunIdentity


def finalize_artifact(*, store: CheckpointStore, identity: RunIdentity, hp: LoRAHyperparameters, export_adapter: Callable[[Path], None],
                      record_count: int, total_steps: int, gpu: str, rates: ResourceRates | None,
                      clock: Callable[[], dt.datetime]) -> ArtifactManifest:
    """Write `final/` exactly once: adapter files + artifact_manifest.json, published by an atomic rename. Calling it
    again for a finished run returns the existing, re-verified manifest instead of writing anything."""
    if store.final_dir.exists():
        existing = load_manifest(store.final_dir / MANIFEST_FILENAME)
        verify_adapter_dir(existing, store.final_dir)
        return existing
    ledger = store.read_ledger()
    segments = tuple(Segment(start_step=l.start_step, end_step=l.end_step, duration_seconds=l.duration_seconds)
                     for l in ledger.launches)
    if not segments or segments[-1].end_step != total_steps:
        raise ArtifactError("run_incomplete", "the last launch did not reach the final step")
    tmp = store.run_dir / f".final-{uuid.uuid4().hex}"
    tmp.mkdir()
    try:
        export_adapter(tmp)
        files = hash_adapter_dir(tmp)
        duration = sum(s.duration_seconds for s in segments)
        cost = basis = None
        if rates is not None:  # only ever from caller-supplied, dated rates and measured seconds
            cost = Decimal(duration) * (rates.gpu_per_second + rates.cpu_cores * rates.cpu_per_core_second
                                        + rates.memory_gib * rates.memory_per_gib_second)
            cost, basis = str(cost), f"measured {duration:.1f}s x {rates.source} as of {rates.as_of}"
        manifest = seal_manifest(
            run_id=identity.run_id, base_model=identity.base_model, base_revision=identity.base_revision,
            adapter_files=files, training_manifest_hash=identity.training_manifest_hash, dataset_hash=identity.dataset_hash,
            dataset_record_count=record_count, plan_hash=identity.plan_hash, hyperparameters=identity.hyperparameters,
            total_steps=total_steps, steps_completed=total_steps,
            epochs_completed=max(1, total_steps // hp.steps_per_epoch(record_count)),
            checkpoint_lineage=ledger.lineage, segments=segments, gpu=gpu, cost_usd=cost, cost_basis=basis,
            created_at=clock())
        write_manifest(manifest, tmp / MANIFEST_FILENAME)
        verify_adapter_dir(manifest, tmp)
        for path in tmp.rglob("*"):
            if path.is_file():
                fd = os.open(path, os.O_RDONLY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
        os.rename(tmp, store.final_dir)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return manifest
