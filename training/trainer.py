"""Backend-agnostic training loop: deterministic data schedule, durable checkpoints, genuine resume, budget stops and
finalization. The numerics live in a `TrainBackend` (training.torch_backend is the production one); this module owns
everything that decides WHAT gets trained, WHEN state is saved and WHETHER a run may be called finished.

Resume is real, not "reload the weights": the backend restores adapter + optimizer + scheduler + RNG state from the
newest verified checkpoint, and the data position is re-derived from the step counter and cross-checked against the
checkpoint's recorded (epoch, index_in_epoch). Interrupting at step k and resuming yields the same final state as an
uninterrupted run (asserted in tests/test_training_trainer.py with a stateful backend)."""
from __future__ import annotations

import datetime as dt
import random
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from modal_app.adapter_artifact import ArtifactManifest
from training.artifacts import finalize_artifact
from training.planning import LoRAHyperparameters, ResourceRates
from training.resume import CheckpointBackend, CheckpointStore, ResumeError, RunIdentity


class TrainBackend(CheckpointBackend, Protocol):
    def train_step(self, example_indices: Sequence[int]) -> float:
        """One optimizer step over exactly these dataset rows (micro-batching / accumulation is the backend's job).
        Returns the mean training loss of the step."""

    def export_adapter(self, directory: Path) -> None:
        """Write the adapter files (and nothing else: no base weights, no optimizer) into `directory`."""


def position(step: int, hp: LoRAHyperparameters, record_count: int) -> tuple[int, int]:
    """(epoch, optimizer steps already taken in that epoch) after `step` completed steps."""
    per_epoch = hp.steps_per_epoch(record_count)
    return step // per_epoch, step % per_epoch


def batch_indices(step: int, hp: LoRAHyperparameters, record_count: int) -> list[int]:
    """Dataset rows consumed by optimizer step `step` (0-based): a pure function of (seed, step), so the sampler
    position never needs to be 'remembered' beyond the step counter. Each epoch is a fresh seeded permutation."""
    per_epoch = hp.steps_per_epoch(record_count)
    epoch, within = divmod(step, per_epoch)
    order = list(range(record_count))
    random.Random(f"{hp.seed}:{epoch}").shuffle(order)
    size = hp.examples_per_step()
    return order[within * size:(within + 1) * size]


@dataclass(frozen=True)
class RunOutcome:
    status: str                       # "final" | "paused"
    step: int
    total_steps: int
    manifest: ArtifactManifest | None  # present iff status == "final"
    resumed_from_step: int            # 0 for a fresh start
    losses: tuple[float, ...]


def run_training(*, store: CheckpointStore, identity: RunIdentity, backend: TrainBackend, hp: LoRAHyperparameters,
                 record_count: int, total_budget_seconds: float, gpu: str, rates: ResourceRates | None = None,
                 stop_after_steps: int | None = None, monotonic: Callable[[], float] = time.monotonic,
                 clock: Callable[[], dt.datetime] | None = None, keep_checkpoints: int = 2,
                 on_durable: Callable[[], None] = lambda: None) -> RunOutcome:
    """Run or resume `identity.run_id` until the final step, the per-launch budget, or `stop_after_steps`.

    * total_budget_seconds is the whole-run wall-clock ceiling (derived from the approved cost ceiling); earlier
      launches count against it, hard-killed ones at their full allowance.
    * Reaching the budget or stop point saves a checkpoint and returns status "paused": never "final".
    * A finished run returns its existing verified manifest and executes zero further steps (idempotent)."""
    clock = clock or store.clock
    total_steps = hp.total_steps(record_count)
    store.init_run()
    if store.final_dir.exists():  # finished run: re-verify and return it, execute nothing
        manifest = finalize_artifact(store=store, identity=identity, hp=hp, export_adapter=backend.export_adapter,
                                     record_count=record_count, total_steps=total_steps, gpu=gpu, rates=rates, clock=clock)
        return RunOutcome("final", total_steps, total_steps, manifest, total_steps, ())

    resumed = store.latest_valid()
    step, losses, resumed_from = 0, [], 0
    if resumed is not None:
        meta, directory = resumed
        if (meta.epoch, meta.index_in_epoch) != position(meta.step, hp, record_count):
            raise ResumeError("corrupt_checkpoint", "recorded data position disagrees with the step counter")
        if len(meta.loss_history) != meta.step:
            raise ResumeError("corrupt_checkpoint", "loss history length disagrees with the step counter")
        backend.restore(directory)
        step, losses, resumed_from = meta.step, list(meta.loss_history), meta.step

    remaining = total_budget_seconds - store.read_ledger().consumed_seconds_upper_bound(clock())
    if remaining <= 0 and step < total_steps:
        raise ResumeError("budget_exhausted", "the approved wall-clock budget for this run is already spent")
    launch = store.begin_launch(budget_seconds=max(remaining, 1e-6), start_step=step)
    started, last_saved = monotonic(), step
    pause = False

    def save() -> None:
        nonlocal last_saved
        epoch, within = position(step, hp, record_count)
        store.save(step=step, epoch=epoch, index_in_epoch=within, loss_history=tuple(losses), backend=backend)
        store.prune(keep_checkpoints)
        last_saved = step
        store.record_progress(launch, end_step=step, duration_seconds=monotonic() - started)
        on_durable()  # e.g. Modal Volume.commit(): the checkpoint is not durable until the volume says so

    while step < total_steps:
        losses.append(float(backend.train_step(batch_indices(step, hp, record_count))))
        step += 1
        if step == total_steps or step % hp.checkpoint_every_steps == 0:
            save()
        if step < total_steps and ((stop_after_steps is not None and step - resumed_from >= stop_after_steps)
                                   or monotonic() - started >= remaining):
            pause = True
            break
    if pause:
        if last_saved != step:
            save()
        store.record_progress(launch, end_step=step, duration_seconds=monotonic() - started, close=True, status="paused")
        on_durable()
        return RunOutcome("paused", step, total_steps, None, resumed_from, tuple(losses))

    duration = monotonic() - started
    store.record_progress(launch, end_step=step, duration_seconds=duration, close=True)
    manifest = finalize_artifact(store=store, identity=identity, hp=hp, export_adapter=backend.export_adapter,
                                 record_count=record_count, total_steps=total_steps, gpu=gpu, rates=rates, clock=clock)
    store.record_progress(launch, end_step=step, duration_seconds=duration, close=True, status="final")
    on_durable()
    return RunOutcome("final", step, total_steps, manifest, resumed_from, tuple(losses))
