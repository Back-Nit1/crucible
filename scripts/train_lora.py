"""Plan or launch a LoRA/QLoRA SFT run over curated survivor traces on Modal.

  # offline, free: validate records + manifest, build the shard and the cost-bounded plan, write docs/model-runs/<run>/
  uv run python -m scripts.train_lora --records docs/runs/<gen>/sft.jsonl --manifest docs/runs/<gen>/training_manifest.json \\
      --run-id <run-id> --max-cost 0.50 --plan-only

  # spends money; refuses unless every gate in training.gates is satisfied for THIS manifest hash. Safe to re-run: the same
  # run id resumes from its last verified checkpoint, and a finished run just returns its artifact.
  uv run python -m scripts.train_lora ... --launch [--stop-after-steps N] [--max-steps N] --env-file <.env>

Statuses written to <out>/training_run.json: planned (nothing ran) | blocked_not_run | paused | trained. `trained` is written
only when the server returns a final artifact manifest that passes verification and matches this plan.
The shard (raw training data) is never written unless --write-shard, and is git-ignored."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

from modal_app.adapter_artifact import ArtifactManifest
from modal_app.train_protocol import TrainRequest, TrainResponse
from training.checkpoints import adapter_reference, artifact_ref
from training.curation import SFTRecord, TrainingManifest
from training.dataset import DatasetError, build_dataset
from training.gates import (MAX_LAUNCH_SECONDS, TRAIN_CEILING_VAR, TRAIN_MANIFEST_VAR, GateError, affordable_seconds,
                            authorize_training, list_rates)
from training.planning import LoRAHyperparameters, build_lora_plan, plan_hash
from modal_app.qwen_toolcalls import GPU_TYPE, MODEL_ID, MODEL_REVISION

KEYS = {"CRUCIBLE_MODAL_TOKEN_ROTATED", "CRUCIBLE_MODAL_BILLING_CONFIRMED", TRAIN_CEILING_VAR, TRAIN_MANIFEST_VAR}
Transport = Callable[[dict], dict]


def modal_train_transport(app_name: str = "crucible-qwen-training", function: str = "train") -> Transport:
    """Real transport; requires an already-deployed app. Constructing it starts nothing."""
    import modal
    fn = modal.Function.from_name(app_name, function)
    return lambda payload: fn.remote(payload)


def _write(out: Path, name: str, body: dict) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / name).write_text(json.dumps(body, indent=2, sort_keys=True) + "\n")


def load_records(path: Path) -> tuple[SFTRecord, ...]:
    return tuple(SFTRecord.model_validate_json(line) for line in path.read_text().splitlines() if line.strip())


def launch_commands(args: argparse.Namespace) -> list[str]:
    base = (f"uv run python -m scripts.train_lora --records {args.records} --manifest {args.manifest} --run-id {args.run_id} "
            f"--max-cost {args.max_cost} --env-file <ENV_FILE>")
    return [
        f"export {TRAIN_MANIFEST_VAR}=<training manifest content_hash printed in training_plan.json>",
        f"export {TRAIN_CEILING_VAR}=<your approved USD ceiling for this run>",
        "export CRUCIBLE_MODAL_TOKEN_ROTATED=1 CRUCIBLE_MODAL_BILLING_CONFIRMED=1   # only after rotating the token and adding billing",
        "CRUCIBLE_ENABLE_L4_TRAIN=1 uv run modal deploy modal_app/training.py",
        base + " --launch --max-steps 4 --stop-after-steps 2   # smoke: interrupt after 2 steps",
        base + " --launch --max-steps 4                         # resume the same run id to the end",
        "uv run modal app stop crucible-qwen-training",
        "# before training on real traces, audit split/product leakage with the evaluation branch's scripts.audit_split_leakage "
        "--training-manifest <training_manifest.json> (owned by the evaluation workstream)",
    ]


def main(argv=None, *, transport: Transport | None = None, now: Callable[[], dt.datetime] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--records", type=Path, required=True)
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--max-cost", type=Decimal, required=True, help="USD ceiling this plan may spend (must not exceed the approved ceiling)")
    ap.add_argument("--epochs", type=int, default=1)
    ap.add_argument("--max-steps", type=int)
    ap.add_argument("--learning-rate", type=Decimal, default=Decimal("0.0002"))
    ap.add_argument("--stop-after-steps", type=int)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--env-file")
    ap.add_argument("--allow-scripted-traces", action="store_true",
                    help="train on traces produced by the scripted (oracle) shopper; they read the answer key")
    ap.add_argument("--write-shard", action="store_true")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan-only", action="store_true")
    mode.add_argument("--launch", action="store_true")
    args = ap.parse_args(argv)
    now = now or (lambda: dt.datetime.now(dt.timezone.utc))
    out = args.out or Path("docs/model-runs") / args.run_id
    if args.env_file:
        from scripts._env import load
        load(args.env_file, KEYS)

    try:
        manifest = TrainingManifest.model_validate_json(args.manifest.read_text())
        records = load_records(args.records)
        if manifest.model_version.startswith("scripted") and not args.allow_scripted_traces:
            raise DatasetError("scripted_traces", "these traces come from the scripted oracle shopper; pass --allow-scripted-traces "
                               "to train on them knowingly (pipeline evidence only, not a model-quality claim)")
        dataset = build_dataset(records, manifest)
        hp = LoRAHyperparameters(epochs=args.epochs, learning_rate=args.learning_rate, max_steps=args.max_steps)
        plan = build_lora_plan(manifest, base_model=MODEL_ID, base_revision=MODEL_REVISION, gpu=GPU_TYPE,
                               maximum_approved_cost=args.max_cost, hyperparameters=hp)
    except (DatasetError, ValueError) as exc:
        print(json.dumps({"status": "refused", "detail": str(exc)[:300]}))
        return 2

    rates = list_rates()
    summary = {"run_id": args.run_id, "base_model": MODEL_ID, "base_revision": MODEL_REVISION,
               "training_manifest_hash": manifest.content_hash, "training_data_source": manifest.model_version,
               "dataset_hash": dataset.dataset_hash, "record_count": dataset.record_count, "plan_hash": plan_hash(plan),
               "total_steps": hp.total_steps(dataset.record_count), "hyperparameters": hp.model_dump(mode="json"),
               "gpu": plan.gpu, "maximum_approved_cost_usd": str(plan.maximum_approved_cost),
               "budget_seconds_at_list_rates": affordable_seconds(plan.maximum_approved_cost, rates),
               "max_launch_seconds": MAX_LAUNCH_SECONDS, "rates": rates.model_dump(mode="json")}
    if args.write_shard:
        out.mkdir(parents=True, exist_ok=True)
        (out / "dataset.jsonl").write_bytes(dataset.shard)

    if args.plan_only:
        _write(out, "training_plan.json", {"status": "planned", "trained": False,
                                           "note": "nothing ran: no GPU was allocated and no adapter exists", **summary,
                                           "launch_commands": launch_commands(args)})
        print(json.dumps({"status": "planned", "plan_hash": summary["plan_hash"], "dataset_hash": dataset.dataset_hash}))
        return 0

    try:
        approval = authorize_training(plan)
    except GateError as exc:
        _write(out, "training_run.json", {"status": "blocked_not_run", "trained": False, "blocker": str(exc), "gpu_spend_usd": "0", **summary})
        print(json.dumps({"status": "blocked_not_run", "detail": str(exc)}))
        return 3
    request = TrainRequest(run_id=args.run_id, plan=plan, shard=dataset.shard.decode(), dataset_hash=dataset.dataset_hash,
                           approval=approval, stop_after_steps=args.stop_after_steps)
    try:
        raw = (transport or modal_train_transport())(request.model_dump(mode="json"))
        response = TrainResponse.model_validate(raw)
    except Exception as exc:  # no message text: transport errors may carry URLs or credentials
        _write(out, "training_run.json", {"status": "failed", "trained": False, "error": type(exc).__name__, **summary})
        print(json.dumps({"status": "failed", "error": type(exc).__name__}))
        return 1
    if response.status != "final":
        _write(out, "training_run.json", {"status": "paused", "trained": False, "step": response.step,
                                          "total_steps": response.total_steps, "resumed_from_step": response.resumed_from_step, **summary})
        print(json.dumps({"status": "paused", "step": response.step, "total_steps": response.total_steps}))
        return 0
    try:
        artifact = ArtifactManifest.model_validate(response.manifest)  # re-verifies every hash in the sealed manifest
        assert (artifact.training_manifest_hash, artifact.dataset_hash, artifact.plan_hash, artifact.run_id) == (
            manifest.content_hash, dataset.dataset_hash, summary["plan_hash"], args.run_id)
        assert (artifact.base_model, artifact.base_revision) == (MODEL_ID, MODEL_REVISION)
    except Exception:
        _write(out, "training_run.json", {"status": "failed", "trained": False, "error": "artifact_verification_failed", **summary})
        print(json.dumps({"status": "failed", "error": "artifact_verification_failed"}))
        return 1
    _write(out, "artifact_manifest.json", artifact.model_dump(mode="json"))
    _write(out, "adapter_ref.json", adapter_reference(artifact))  # the reference Agent 2's eval.contenders consumes
    _write(out, "training_run.json", {"status": "trained", "trained": True, "checkpoint_id": artifact.checkpoint_id,
                                      "artifact_ref": artifact_ref(artifact), "adapter_hash": artifact.adapter_hash,
                                      "measured_duration_seconds": artifact.duration_seconds, "cost_usd": artifact.cost_usd,
                                      "cost_basis": artifact.cost_basis, "completed_at": now().isoformat(), **summary})
    print(json.dumps({"status": "trained", "checkpoint_id": artifact.checkpoint_id, "artifact_ref": artifact_ref(artifact)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
