"""Container-side training service: turns one TrainRequest into a (resumable) run. Everything heavy is injected
(`backend_factory`, `volume_commit`, clocks), so the same code path runs on Modal and in offline tests; the only thing
a test replaces is the numerics, never the verification, resume or finalization logic.

Re-verified here regardless of what the caller already checked: pinned model/revision, GPU type, shard hash, shard <->
manifest binding, plan <-> shard record count, and that the approval's budget cannot cost more than its ceiling."""
from __future__ import annotations

import datetime as dt
import time
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

from modal_app.adapter_artifact import canonical_bytes
from modal_app.qwen_toolcalls import GPU_TYPE, MODEL_ID, MODEL_REVISION
from modal_app.train_protocol import TrainRequest, TrainResponse
from training.gates import MAX_LAUNCH_SECONDS, GateError, cost_per_second
from training.planning import plan_hash
from training.resume import CheckpointStore, RunIdentity, atomic_write_bytes
from training.shard import Shard, parse_shard
from training.trainer import TrainBackend, run_training

BackendFactory = Callable[[Shard, "object", int], TrainBackend]  # (shard, hyperparameters, total_steps) -> backend


def check_request(request: TrainRequest) -> None:
    plan, approval = request.plan, request.approval
    if (plan.base_model, plan.base_revision) != (MODEL_ID, MODEL_REVISION):
        raise GateError("unpinned_model", "plan does not use the pinned base model and revision")
    if plan.gpu != GPU_TYPE:
        raise GateError("unsupported_gpu", f"only {GPU_TYPE} is supported")
    if approval.manifest_hash != plan.training_manifest_hash:
        raise GateError("approved_manifest_mismatch", "approval is for a different training manifest")
    if plan.maximum_approved_cost > approval.ceiling_usd:
        raise GateError("plan_exceeds_ceiling", "plan cost exceeds the approved ceiling")
    if Decimal(str(approval.budget_seconds)) * cost_per_second(approval.rates) > min(plan.maximum_approved_cost, approval.ceiling_usd):
        raise GateError("budget_exceeds_ceiling", "approval budget_seconds would cost more than the approved ceiling")


def execute(request: TrainRequest, *, runs_root: Path, backend_factory: BackendFactory, signature: str,
            volume_commit: Callable[[], None] = lambda: None, monotonic: Callable[[], float] = time.monotonic,
            clock: Callable[[], dt.datetime] | None = None) -> TrainResponse:
    check_request(request)
    plan = request.plan
    shard = parse_shard(request.shard.encode(), expected_dataset_hash=request.dataset_hash,
                        expected_manifest_hash=plan.training_manifest_hash)
    if plan.record_count != len(shard.examples):
        raise GateError("record_count_mismatch", "plan.record_count disagrees with the shard")
    hp = plan.hyperparameters
    total_steps = hp.total_steps(len(shard.examples))
    identity = RunIdentity(
        run_id=request.run_id, plan_hash=plan_hash(plan), base_model=plan.base_model, base_revision=plan.base_revision,
        training_manifest_hash=plan.training_manifest_hash, dataset_hash=request.dataset_hash,
        data_source_model_version=shard.source_model_version or "unspecified-source-model",
        hyperparameters=hp.model_dump(mode="json"), backend_signature=signature)
    store = CheckpointStore(runs_root, identity, clock=clock)
    store.init_run()  # idempotent; raises incompatible_run if this run id exists with another identity
    dataset_path = store.run_dir / "dataset.jsonl"
    if dataset_path.exists():
        if dataset_path.read_bytes() != request.shard.encode():
            raise GateError("dataset_changed", "run already has a different dataset shard")
    else:
        atomic_write_bytes(dataset_path, request.shard.encode())
    backend = backend_factory(shard, hp, total_steps)
    outcome = run_training(
        store=store, identity=identity, backend=backend, hp=hp, record_count=len(shard.examples),
        total_budget_seconds=request.approval.budget_seconds, gpu=plan.gpu, rates=request.approval.rates,
        stop_after_steps=request.stop_after_steps, monotonic=monotonic, clock=clock, on_durable=volume_commit,
        max_launch_seconds=MAX_LAUNCH_SECONDS)
    volume_commit()
    manifest = outcome.manifest
    return TrainResponse(status=outcome.status, run_id=request.run_id, step=outcome.step, total_steps=outcome.total_steps,
                         resumed_from_step=outcome.resumed_from_step,
                         checkpoint_id=manifest.checkpoint_id if manifest else None,
                         manifest=manifest.model_dump(mode="json") if manifest else None)
