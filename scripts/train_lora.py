"""Plan or launch a LoRA/QLoRA run on Modal: SFT over curated survivor traces, or GRPO over world rollouts.

  # offline, free: validate records + manifest, build the shard and the cost-bounded plan, write docs/model-runs/<run>/
  uv run python -m scripts.train_lora --records docs/runs/<gen>/sft.jsonl --manifest docs/runs/<gen>/training_manifest.json \\
      --run-id <run-id> --max-cost 0.50 --plan-only

  # spends money; refuses unless every gate in training.gates is satisfied for THIS manifest hash. Safe to re-run: the same
  # run id resumes from its last verified checkpoint, and a finished run just returns its artifact.
  uv run python -m scripts.train_lora ... --launch [--stop-after-steps N] [--max-steps N] --env-file <.env>

  # GRPO (docs/model-runs/GRPO.md): every rollout of the checkpoint being updated, K per task; own gates (CRUCIBLE_MODAL_RL_*)
  uv run python -m scripts.train_lora --algorithm grpo --rollouts <gen>/rollouts.jsonl [--policy-adapter-manifest <final/
      artifact_manifest.json>] --run-id <run-id> --max-cost 0.50 --plan-only

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
from training.gates import (MAX_LAUNCH_SECONDS, RL_CEILING_VAR, RL_ROLLOUTS_VAR, TRAIN_CEILING_VAR, TRAIN_MANIFEST_VAR, GateError,
                            affordable_seconds, authorize_training, cost_per_second, gate_vars, list_rates)
from training.planning import GRPOConfig, LoRAHyperparameters, ResourceRates, build_lora_plan, plan_hash
from modal_app.qwen_toolcalls import GPU_TYPE, MODEL_ID, MODEL_REVISION

KEYS = {"CRUCIBLE_MODAL_TOKEN_ROTATED", "CRUCIBLE_MODAL_BILLING_CONFIRMED", TRAIN_CEILING_VAR, TRAIN_MANIFEST_VAR,
        RL_CEILING_VAR, RL_ROLLOUTS_VAR}
_Q = Decimal("0.000001")
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
    grpo = args.algorithm == "grpo"
    data = (f"--algorithm grpo --rollouts {args.rollouts}" + (f" --policy-adapter-manifest {args.policy_adapter_manifest}"
                                                             if args.policy_adapter_manifest else "")
            if grpo else f"--records {args.records} --manifest {args.manifest}")
    base = (f"uv run python -m scripts.train_lora {data} --run-id {args.run_id} "
            f"--max-cost {args.max_cost} --taskset {args.taskset} --env-file <ENV_FILE>")
    ceiling_var, hash_var = (RL_CEILING_VAR, RL_ROLLOUTS_VAR) if grpo else (TRAIN_CEILING_VAR, TRAIN_MANIFEST_VAR)
    return [
        f"export {hash_var}=<training_manifest_hash printed in training_plan.json>",
        f"export {ceiling_var}=<your approved USD ceiling for this run>",
        "export CRUCIBLE_MODAL_TOKEN_ROTATED=1 CRUCIBLE_MODAL_BILLING_CONFIRMED=1   # only after rotating the token and adding billing",
        f"CRUCIBLE_ENABLE_L4_{'RL' if grpo else 'TRAIN'}=1 uv run modal deploy modal_app/qwen_training.py",
        base + " --launch --max-steps 4 --stop-after-steps 2   # smoke: interrupt after 2 steps",
        base + " --launch --max-steps 4                         # resume the same run id to the end",
        "uv run modal app stop crucible-qwen-training",
        "# train_lora re-runs scripts.audit_split_leakage with this training manifest before either launch command",
    ]


def policy_fields(path: Path | None) -> dict[str, str]:
    """GRPO updates the checkpoint its rollouts came from: base (no manifest) or one sealed adapter on the pinned base."""
    if path is None:
        return {}
    from modal_app.adapter_artifact import load_manifest
    m = load_manifest(path)
    if (m.base_model, m.base_revision) != (MODEL_ID, MODEL_REVISION):
        raise DatasetError("unpinned_policy", "the policy adapter was trained on a different base model or revision")
    return {"policy_checkpoint": m.checkpoint_id, "policy_adapter_run_id": m.run_id, "policy_adapter_hash": m.adapter_hash}


def rl_cost(rollouts, max_cost: Decimal, rates: ResourceRates, seconds_per_call: int) -> dict:
    """Upper bounds at list rates: re-producing these rollouts (episodes x max model calls x seconds per call, no
    wall-clock cap assumed, so at least as large as scripts.run_loop --plan's capped bound) plus the update's budget."""
    from agents.runner import RunnerConfig
    rate = cost_per_second(rates)
    cfg = RunnerConfig()
    calls = cfg.max_tool_calls * cfg.max_calls_per_step
    sizes: dict[str, int] = {}
    for r in rollouts:
        sizes[r.group_id] = sizes.get(r.group_id, 0) + 1
    seconds = len(rollouts) * calls * seconds_per_call
    budget = min(affordable_seconds(max_cost, rates), MAX_LAUNCH_SECONDS * 4)
    inference = {"episodes": len(rollouts), "tasks": len({r.task_id for r in rollouts}), "max_group_size": max(sizes.values()),
                 "max_model_calls": len(rollouts) * calls, "seconds_per_call": seconds_per_call, "max_seconds": seconds,
                 "max_cost_usd": str((seconds * rate).quantize(_Q)),
                 "note": "bound for producing these rollouts (already spent if a model produced them); approved by "
                         "CRUCIBLE_MODAL_APPROVED_CEILING_USD in the generation stage, not by this run"}
    update = {"budget_seconds": budget, "max_cost_usd": str((budget * rate).quantize(_Q))}
    return {"rate_usd_per_second": str(rate), "rollout_inference": inference, "update": update,
            "max_cost_usd": str(Decimal(inference["max_cost_usd"]) + Decimal(update["max_cost_usd"]))}


def main(argv=None, *, transport: Transport | None = None, now: Callable[[], dt.datetime] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--algorithm", choices=["sft", "grpo"], default="sft")
    ap.add_argument("--records", type=Path, help="sft: curated SFT records")
    ap.add_argument("--manifest", type=Path, help="sft: their training manifest")
    ap.add_argument("--rollouts", type=Path, help="grpo: rollouts.jsonl (training.rollouts) from the policy being updated")
    ap.add_argument("--policy-adapter-manifest", type=Path,
                    help="grpo: sealed artifact_manifest.json of the adapter the rollouts came from (omit = base model)")
    defaults = GRPOConfig()
    ap.add_argument("--kl-beta", type=Decimal, default=defaults.kl_beta)
    ap.add_argument("--clip-epsilon", type=Decimal, default=defaults.clip_epsilon)
    ap.add_argument("--reward-floor", type=Decimal, default=defaults.reward_floor, help="grpo: reward of killed / unscored episodes")
    ap.add_argument("--min-group-size", type=int, default=defaults.min_group_size)
    ap.add_argument("--seconds-per-call", type=int, default=120, help="grpo cost bound: billable seconds per model call")
    ap.add_argument("--taskset", type=Path, default=Path("docs/evaluations/taskset-20261110"),
                    help="audited protected/reference task-set directory used to gate this training manifest")
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
    if args.algorithm == "sft" and not (args.records and args.manifest):
        ap.error("sft needs --records and --manifest")
    if args.algorithm == "grpo" and not args.rollouts:
        ap.error("grpo needs --rollouts")
    now = now or (lambda: dt.datetime.now(dt.timezone.utc))
    out = args.out or Path("docs/model-runs") / args.run_id
    if args.env_file:
        from scripts._env import load
        load(args.env_file, KEYS)

    rl = None
    try:
        hp_fields = dict(epochs=args.epochs, learning_rate=args.learning_rate, max_steps=args.max_steps)
        if args.algorithm == "grpo":
            from training.rl.dataset import build_rl_dataset
            from training.rollouts import RolloutRecord
            rollouts = tuple(RolloutRecord.model_validate_json(line) for line in args.rollouts.read_text().splitlines() if line.strip())
            cfg = GRPOConfig(kl_beta=args.kl_beta, clip_epsilon=args.clip_epsilon, reward_floor=args.reward_floor,
                             min_group_size=args.min_group_size, **policy_fields(args.policy_adapter_manifest))
            rl = build_rl_dataset(rollouts, cfg, created_at=now(), allow_scripted=args.allow_scripted_traces)
            manifest, dataset = rl.manifest, rl.dataset
            manifest_path = out / "rollout_manifest.json"  # the audited view of the rollout set (content_hash = rollout set hash)
            out.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(manifest.model_dump_json(indent=2) + "\n")
            hp = LoRAHyperparameters(method="qlora_grpo", grpo=cfg, **hp_fields)
        else:
            manifest, manifest_path = TrainingManifest.model_validate_json(args.manifest.read_text()), args.manifest
            if manifest.model_version.startswith("scripted") and not args.allow_scripted_traces:
                raise DatasetError("scripted_traces", "these traces come from the scripted oracle shopper; pass --allow-scripted-traces "
                                   "to train on them knowingly (pipeline evidence only, not a model-quality claim)")
            dataset = None  # built after the audit, as before GRPO existed
            hp = LoRAHyperparameters(**hp_fields)
        from scripts.audit_split_leakage import audit_paths
        taskset_meta = json.loads((args.taskset / "taskset.json").read_text())
        audit_report = audit_paths(protected_path=args.taskset / "protected.jsonl",
                                   reference_path=args.taskset / "reference.jsonl",
                                   training_manifest_paths=(manifest_path,),
                                   protected_hash=taskset_meta["protected_hash"],
                                   reference_hash=taskset_meta["reference_hash"],
                                   allow_not_run=frozenset({"memory_eligibility"}))
        if not audit_report.passed:
            failed = ", ".join(name for name, check in audit_report.checks.items() if check.status != "pass")
            raise DatasetError("split_leakage", f"training manifest failed the protected/reference audit: {failed}")
        dataset = dataset or build_dataset(load_records(args.records), manifest)
        plan = build_lora_plan(manifest, base_model=MODEL_ID, base_revision=MODEL_REVISION, gpu=GPU_TYPE,
                               maximum_approved_cost=args.max_cost, hyperparameters=hp, record_count=dataset.record_count)
    except (DatasetError, ValueError, OSError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "refused", "detail": str(exc)[:300]}))
        return 2

    rates = list_rates()
    summary = {"run_id": args.run_id, "algorithm": hp.algorithm, "base_model": MODEL_ID, "base_revision": MODEL_REVISION,
               "training_manifest_hash": manifest.content_hash, "training_data_source": manifest.model_version,
               "leakage_audit_hash": audit_report.content_hash, "taskset": str(args.taskset),
               "dataset_hash": dataset.dataset_hash, "record_count": dataset.record_count, "plan_hash": plan_hash(plan),
               "total_steps": hp.total_steps(dataset.record_count), "hyperparameters": hp.model_dump(mode="json"),
               "gpu": plan.gpu, "maximum_approved_cost_usd": str(plan.maximum_approved_cost),
               "budget_seconds_at_list_rates": affordable_seconds(plan.maximum_approved_cost, rates),
               "max_launch_seconds": MAX_LAUNCH_SECONDS, "rates": rates.model_dump(mode="json")}
    if rl is not None:
        ceiling_var, hash_var = gate_vars(plan)
        used = set(manifest.source_episode_ids)
        summary["rl"] = {"rollout_set_hash": manifest.content_hash, "stats": rl.stats,
                         "cost": rl_cost([r for r in rollouts if r.episode_id in used],
                                         plan.maximum_approved_cost, rates, args.seconds_per_call),
                         "env": {"CRUCIBLE_MODAL_TOKEN_ROTATED": "1", "CRUCIBLE_MODAL_BILLING_CONFIRMED": "1",
                                 ceiling_var: str(plan.maximum_approved_cost), hash_var: manifest.content_hash},
                         "deploy_env": {"CRUCIBLE_ENABLE_L4_RL": "1"}}
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
