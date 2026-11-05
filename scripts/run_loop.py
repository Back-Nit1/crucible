"""One resumable expert-iteration: generation (real model) -> curation -> leakage audit -> LoRA plan -> gated train ->
gated evaluation -> re-entry of the adapter into the next population.

  uv run python -m scripts.run_loop --iteration-id it-1 --env-file <ENV_FILE>                    # real; stops at the first gate
  uv run python -m scripts.run_loop --iteration-id it-2 --adapter-manifest <it-1 artifact_manifest.json> --env-file <ENV_FILE>
  uv run python -m scripts.run_loop --iteration-id dry-1 --dry-run                               # offline, scripted, $0

Each stage writes <root>/<iteration>/stages/<stage>.json; rerunning resumes at the first stage not `done`. A missing gate
variable stops the loop with exit 3 and names the variable(s). `--dry-run` uses the scripted oracle shopper (it reads the
answer key), the synthetic catalog, `--allow-scripted-traces` and an offline null trainer: pipeline evidence only — its
"adapter" is a placeholder file, never a model. Exit codes: 0 ok/paused, 1 failed, 2 refused, 3 blocked by a gate, 4 stopped by the kill switch (<root>/STOP).
Model calls retry only transient errors and each episode is capped at RunnerConfig.max_episode_seconds."""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import re
import sys
from decimal import Decimal
from pathlib import Path

from training.gates import RL_CEILING_VAR, RL_ROLLOUTS_VAR, TRAIN_CEILING_VAR, TRAIN_MANIFEST_VAR

STAGES = ("generate", "curate", "audit", "plan", "train", "evaluate", "reenter")
INFERENCE_VARS = ("CRUCIBLE_MODAL_TOKEN_ROTATED", "CRUCIBLE_MODAL_BILLING_CONFIRMED", "CRUCIBLE_MODAL_APPROVED_CEILING_USD")
TRAIN_VARS = (TRAIN_CEILING_VAR, TRAIN_MANIFEST_VAR)
RL_VARS = (RL_CEILING_VAR, RL_ROLLOUTS_VAR)
GATE_VARS = INFERENCE_VARS + TRAIN_VARS + RL_VARS
ELASTIC_VARS = ("ELASTIC_API_KEY", "ELASTIC_ENDPOINT", "ELASTIC_CLOUD_ID")
DRY_EVIDENCE, MODEL_EVIDENCE = "pipeline_evidence_scripted_dry_run", "model_rollouts"
NOW = dt.datetime(2026, 11, 1, tzinfo=dt.UTC)  # dry-run clock: identical inputs, identical artifacts


class Stop(Exception):
    def __init__(self, code: int, status: str, detail: str, **extra):
        super().__init__(detail)
        self.code, self.status, self.extra = code, status, {"detail": detail, **extra}


def _missing(message: str) -> list[str]:
    """Gate errors read `...missing confirmations: A, B`; anything else (e.g. a hash mismatch) names no variable."""
    _, _, names = str(message).partition("missing confirmations: ")
    return [n.strip() for n in names.split(",") if n.strip()]


def _blocked(message: str, fallback: tuple[str, ...] = ()) -> Stop:
    names = _missing(message) or list(fallback)
    return Stop(3, "blocked", str(message), missing=names)


def require_inference_gate() -> None:
    from agents.model import InferenceError
    from agents.qwen_client import require_launch_authorization
    try:
        require_launch_authorization()
    except InferenceError as exc:
        raise _blocked(exc) from None


def _write(path: Path, body: dict) -> None:
    """Atomic: /loop/status may read a stage file while the loop writes it."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(body, indent=1, sort_keys=True) + "\n")
    tmp.replace(path)


def _quiet(fn, *args, **kw):
    """Sub-commands print their own JSON; keep the loop's stdout one JSON document."""
    with contextlib.redirect_stdout(sys.stderr):
        try:
            return fn(*args, **kw)
        except SystemExit as exc:  # argparse / sub-command refusals exit; the loop records them as a stage outcome
            return exc.code if isinstance(exc.code, int) else 2



# --- stages: each takes (args, iteration dir, outputs of earlier stages) and returns this stage's outputs ----------
def generate(a, d: Path, done: dict) -> dict:
    from scripts.run_generation import main as run_generation
    gen = f"{a.iteration_id}-gen"
    argv = ["--seed", str(a.seed), "--population", str(a.population), "--tasks", str(a.tasks), "--generation-id", gen,
            "--iteration-id", a.iteration_id, "--samples-per-task", str(a.samples_per_task),
            "--checkpoint-dir", str(d / "checkpoints"), "--out-dir", str(d / "generation"),
            "--memory", "off"]  # rollout prompts must be exact: retrieved memory is not stored on episodes
    if a.dry_run:
        argv += ["--provider", "synthetic", "--traces", "memory", "--model", "scripted"]
    else:
        if a.adapter_manifest:
            from modal_app.adapter_artifact import load_manifest
            if load_manifest(a.adapter_manifest).data_source_model_version.startswith("scripted"):
                raise Stop(2, "refused", "adapter was trained on scripted oracle traces (a dry run): never re-enters a real run")
        require_inference_gate()
        argv += ["--provider", "elastic_snapshot", "--taskset", str(a.taskset), "--model", "qwen",
                 "--traces", "elastic", *(["--env-file", a.env_file] if a.env_file else []),
                 *(["--adapter-manifest", str(a.adapter_manifest)] if a.adapter_manifest else [])]
    from agents.model import InferenceError
    from world.runtime import ModelUnavailable
    try:
        rc = _quiet(run_generation, argv)
    except (ModelUnavailable, InferenceError) as exc:  # backend down or spend ceiling reached: resumable
        raise Stop(0, "paused", f"{type(exc).__name__}: {getattr(exc, 'code', 'model unavailable')}; rerun to resume") from None
    if rc != 0:
        raise Stop(1, "failed", f"run_generation exited {rc}")
    out = d / "generation" / gen
    if not (out / "training_manifest.json").is_file():
        raise Stop(0, "paused", "generation is not complete yet; rerun to resume")
    rollouts = (out / "rollouts.jsonl").read_text().count("\n")
    return {"generation_dir": str(out), "rollouts": rollouts}


def curate(a, d: Path, done: dict) -> dict:
    out = Path(done["generate"]["generation_dir"])
    report = json.loads((out / "curation_report.json").read_text())
    manifest = json.loads((out / "training_manifest.json").read_text())
    if not report["records"] and a.algorithm == "sft":  # GRPO trains on every rollout, not on curated records
        raise Stop(2, "refused", "curation kept no training records", dropped_by_reason=report["dropped_by_reason"])
    return {"records": report["records"], "dropped_by_reason": report["dropped_by_reason"],
            "training_manifest_hash": manifest["content_hash"], "training_data_source": manifest["model_version"]}


def audit(a, d: Path, done: dict) -> dict:
    from scripts.audit_split_leakage import audit_paths
    meta = json.loads((a.taskset / "taskset.json").read_text())
    report = audit_paths(protected_path=a.taskset / "protected.jsonl", reference_path=a.taskset / "reference.jsonl",
                         training_manifest_paths=(Path(done["generate"]["generation_dir"]) / "training_manifest.json",),
                         protected_hash=meta["protected_hash"], reference_hash=meta["reference_hash"],
                         allow_not_run=frozenset({"memory_eligibility"}))
    if not report.passed:
        raise Stop(2, "refused", "split-leakage audit failed",
                   failed=[n for n, c in report.checks.items() if c.status != "pass"])
    # GRPO trains on every rollout: train_lora audits that rollout manifest itself (its hash is in stages/plan.json)
    return {"audit_hash": report.content_hash, "audited": "curated SFT training manifest"}


def _train_argv(a, done: dict) -> list[str]:
    out = Path(done["generate"]["generation_dir"])
    data = (["--algorithm", "grpo", "--rollouts", str(out / "rollouts.jsonl"),
             *(["--policy-adapter-manifest", str(a.adapter_manifest)] if a.adapter_manifest and not a.dry_run else [])]
            if a.algorithm == "grpo" else ["--records", str(out / "sft.jsonl"), "--manifest", str(out / "training_manifest.json")])
    return [*data, "--taskset", str(a.taskset), "--run-id", f"{a.iteration_id}-{a.algorithm}", "--max-cost", str(a.max_train_cost), "--out", str(a.dir / "train"),
            *(["--max-steps", str(a.max_steps)] if a.max_steps else []),
            *(["--allow-scripted-traces"] if a.dry_run else [])]


def plan(a, d: Path, done: dict) -> dict:
    from scripts.train_lora import main as train_lora
    if (rc := _quiet(train_lora, [*_train_argv(a, done), "--plan-only"])) != 0:
        raise Stop(2, "refused", f"train_lora --plan-only exited {rc}")
    body = json.loads((d / "train" / "training_plan.json").read_text())
    out = {k: body[k] for k in ("plan_hash", "dataset_hash", "training_manifest_hash", "record_count", "total_steps",
                                "maximum_approved_cost_usd", "budget_seconds_at_list_rates")}
    out["leakage_audit_hash"] = body["leakage_audit_hash"]  # the audit of exactly what this algorithm trains on
    if "rl" in body:  # GRPO: its approval binds to the rollout set hash, with its own ceiling variable
        out |= {"rollout_set_hash": body["rl"]["rollout_set_hash"], "gate_env": body["rl"]["env"]}
    return out


def _dry_train(a, d: Path, done: dict) -> dict:
    """Offline: the real training service (verification, resume, sealing) over a null backend. No GPU, no Modal."""
    from modal_app.adapter_artifact import ADAPTER_CONFIG, ADAPTER_WEIGHTS, ArtifactManifest
    from modal_app.qwen_toolcalls import GPU_TYPE, MODEL_ID, MODEL_REVISION
    from modal_app.train_protocol import TrainingApproval, TrainRequest
    from scripts.train_lora import load_records
    from training.curation import TrainingManifest
    from training.dataset import build_dataset
    from training.gates import affordable_seconds, list_rates
    from training.planning import LoRAHyperparameters, build_lora_plan
    from training.service import execute

    run_id = f"{a.iteration_id}-{a.algorithm}"

    class NullBackend:  # deterministic stand-in numerics: the adapter it exports is a labelled placeholder
        n = 0

        def train_step(self, idx):
            self.n += 1
            return 1.0 / self.n

        def capture(self, directory):
            (directory / "null.json").write_text(json.dumps({"n": self.n}))

        def restore(self, directory):
            self.n = json.loads((directory / "null.json").read_text())["n"]

        def export_adapter(self, directory):
            (directory / ADAPTER_CONFIG).write_text('{"dry_run": true}')
            (directory / ADAPTER_WEIGHTS).write_text(f"dry-run placeholder for {run_id}: not a trained adapter")

    out = Path(done["generate"]["generation_dir"])
    hp = dict(max_steps=a.max_steps, checkpoint_every_steps=1)
    if a.algorithm == "grpo":  # Agent B's GRPO dataset over every rollout (scripted allowed: dry run only)
        from training.planning import GRPOConfig
        from training.rl.dataset import build_rl_dataset
        from training.rollouts import RolloutRecord
        rollouts = tuple(RolloutRecord.model_validate_json(x) for x in (out / "rollouts.jsonl").read_text().splitlines() if x)
        rl = build_rl_dataset(rollouts, GRPOConfig(), created_at=NOW, allow_scripted=True)
        manifest, dataset = rl.manifest, rl.dataset
        extra = {"hyperparameters": LoRAHyperparameters(method="qlora_grpo", grpo=GRPOConfig(), **hp),
                 "record_count": dataset.record_count}
    else:
        manifest = TrainingManifest.model_validate_json((out / "training_manifest.json").read_text())
        dataset = build_dataset(load_records(out / "sft.jsonl"), manifest)
        extra = {"hyperparameters": LoRAHyperparameters(**hp)}
    lora = build_lora_plan(manifest, base_model=MODEL_ID, base_revision=MODEL_REVISION, gpu=GPU_TYPE,
                           maximum_approved_cost=a.max_train_cost, **extra)
    rates = list_rates()
    approval = TrainingApproval(ceiling_usd=a.max_train_cost, manifest_hash=manifest.content_hash,
                                budget_seconds=float(affordable_seconds(a.max_train_cost, rates)), rates=rates)
    response = execute(TrainRequest(run_id=run_id, plan=lora, shard=dataset.shard.decode(),
                                    dataset_hash=dataset.dataset_hash, approval=approval),
                       runs_root=d / "train" / "dry-run-volume", backend_factory=lambda s, h, n: NullBackend(),
                       signature="dry-run-null-backend", clock=lambda: NOW, monotonic=lambda: 0.0,
                       **({"algorithms": frozenset({"grpo"})} if a.algorithm == "grpo" else {}))
    artifact = ArtifactManifest.model_validate(response.manifest)
    path = d / "train" / "artifact_manifest.json"
    path.write_text(json.dumps(artifact.model_dump(mode="json"), indent=2, sort_keys=True) + "\n")
    return {"artifact_manifest": str(path), "checkpoint_id": artifact.checkpoint_id, "adapter_hash": artifact.adapter_hash}


def train(a, d: Path, done: dict) -> dict:
    if a.dry_run:
        return _dry_train(a, d, done)
    from scripts.train_lora import main as train_lora
    rc = _quiet(train_lora, [*_train_argv(a, done), "--launch", *(["--env-file", a.env_file] if a.env_file else [])])
    if rc not in (0, 3):  # refused (2) or failed (1): training_run.json may be absent or from an earlier attempt
        raise Stop(rc, "failed" if rc == 1 else "refused", f"train_lora --launch exited {rc}")
    run = json.loads((d / "train" / "training_run.json").read_text())
    if rc == 3:
        raise _blocked(run.get("blocker", ""), tuple(done["plan"].get("gate_env", {})) or TRAIN_VARS)
    if run["status"] != "trained":
        raise Stop(0, "paused", f"training {run['status']} at step {run.get('step')}; rerun to resume")
    return {"artifact_manifest": str(d / "train" / "artifact_manifest.json"), "checkpoint_id": run["checkpoint_id"],
            "adapter_hash": run["adapter_hash"]}


def evaluate(a, d: Path, done: dict) -> dict:
    from eval.runner import EvaluationStore
    from scripts.run_evaluation import main as run_evaluation
    eid, root = f"{a.iteration_id}-eval", d / "eval"
    common = ["--evaluation-id", eid, "--root", str(root)]
    if EvaluationStore(root, eid).load_manifest() is None:  # plan once: a re-plan would stamp a new manifest
        if (rc := _quiet(run_evaluation, ["plan", *common, "--taskset", str(a.taskset),
                                          "--adapter-manifest", done["train"]["artifact_manifest"],
                                          "--seeds", ",".join(str(20261201 + i) for i in range(a.eval_seeds))])) != 0:
            raise Stop(2, "refused", f"run_evaluation plan exited {rc}")
    manifest = EvaluationStore(root, eid).load_manifest()
    if done["train"]["adapter_hash"] not in {c.adapter_sha256 for c in manifest.contenders}:
        raise Stop(2, "refused", f"{eid} was planned for a different adapter: delete {root / eid} to re-plan")
    out = {"evaluation_id": eid, "manifest_hash": manifest.manifest_hash, "contenders": [c.id for c in manifest.contenders]}
    if a.dry_run:
        return out | {"measured": False, "note": "dry run: evaluation planned (leakage-audited, contenders pinned), not run"}
    require_inference_gate()
    env = ["--env-file", a.env_file] if a.env_file else []
    rc = _quiet(run_evaluation, ["run", *common, *env])  # exits 3 itself when a client cannot be authorized
    if rc == 3:
        raise _blocked("inference gate refused the evaluation clients", INFERENCE_VARS)
    if rc != 0:
        raise Stop(1, "failed", f"run_evaluation run exited {rc}")
    try:
        rc = _quiet(run_evaluation, ["report", *common])
    except Exception as exc:  # eval.runner.Incomplete: some pairs still missing
        rc = type(exc).__name__
    if rc != 0:
        raise Stop(0, "paused", f"evaluation not complete yet ({rc}); rerun to resume")
    return out | {"measured": True, "report": str(root / eid / "report.json")}


def reenter(a, d: Path, done: dict) -> dict:
    from training.checkpoints import CheckpointCatalog
    path = Path(done["train"]["artifact_manifest"])
    label = CheckpointCatalog.from_manifest_files([path]).labels()[1]  # verifies every hash before it can re-enter
    stem, _, n = a.iteration_id.rpartition("-")
    nxt = f"{stem}-{int(n) + 1}" if stem and n.isdigit() else f"{a.iteration_id}-2"
    keep = (f"--algorithm {a.algorithm} --taskset {a.taskset} --population {a.population} --tasks {a.tasks} "
            f"--samples-per-task {a.samples_per_task} --max-train-cost {a.max_train_cost}")
    return {"checkpoint": label, "adapter_manifest": str(path),
            "next_command": f"uv run python -m scripts.run_loop --iteration-id {nxt} --adapter-manifest {path} {keep}"
                            + (" --dry-run" if a.dry_run else " --env-file <ENV_FILE>")}


def cost_plan(a) -> dict:
    """Upper bounds at recorded list rates (training.gates): model calls x seconds per call x $/s for inference,
    the trainer's affordable budget seconds for training. Modal billing is the truth; cold start is not measured."""
    from agents.runner import RunnerConfig
    from eval.taskset import load_tasks
    from training.gates import MAX_LAUNCH_SECONDS, affordable_seconds, cost_per_second, list_rates
    from agents.qwen_client import PROBE_CEILING_USD
    rate, q, cfg = cost_per_second(list_rates()), Decimal("0.000001"), RunnerConfig()
    step_calls = cfg.max_calls_per_step
    calls_per_episode = cfg.max_tool_calls * step_calls
    # the wall-clock cap is checked before each step, so the step in flight can still make all its tries
    episode_seconds = min(calls_per_episode * a.seconds_per_call, int(cfg.max_episode_seconds) + step_calls * a.seconds_per_call)
    idle = 60  # qwen_inference scaledown_window, billed once per stage

    def inference(episodes: int) -> dict:
        seconds = episodes * episode_seconds + idle
        return {"episodes": episodes, "max_model_calls": episodes * calls_per_episode, "seconds_per_call": a.seconds_per_call,
                "max_seconds_per_episode": episode_seconds,
                "max_seconds": seconds, "max_cost_usd": str((seconds * rate).quantize(q))}
    gen = inference(a.population * a.tasks * a.samples_per_task)
    contenders = 2  # base-qwen + the trained adapter (no memory pool in the loop)
    protected = len(load_tasks(a.taskset / "protected.jsonl"))
    ev = inference(protected * a.eval_seeds * contenders)
    ev["max_cost_per_client_usd"] = str((Decimal(ev["max_cost_usd"]) / contenders).quantize(q))  # each client has its own cap
    budget = min(affordable_seconds(a.max_train_cost, list_rates()), MAX_LAUNCH_SECONDS * 4)
    free = {"max_cost_usd": "0"}
    stages = {"generate": gen, "curate": free, "audit": free, "plan": free,
              "train": {"algorithm": a.algorithm, "budget_seconds": budget, "max_cost_usd": str((budget * rate).quantize(q))},
              "evaluate": ev, "reenter": free}
    inference_ceiling = max(Decimal(gen["max_cost_usd"]), Decimal(ev["max_cost_per_client_usd"]))
    return {"iteration_id": a.iteration_id, "rate_usd_per_second": str(rate), "rates": list_rates().model_dump(mode="json"),
            "cold_start_seconds": None, "stages": stages,
            "total_max_cost_usd": str(sum(Decimal(s["max_cost_usd"]) for s in stages.values())),
            "env": {"CRUCIBLE_MODAL_TOKEN_ROTATED": "1", "CRUCIBLE_MODAL_BILLING_CONFIRMED": "1",
                    "CRUCIBLE_MODAL_APPROVED_CEILING_USD": str(inference_ceiling),
                    **({RL_VARS[0]: str(a.max_train_cost),
                        RL_VARS[1]: "<rollout_set_hash from stages/plan.json, known after plan>"} if a.algorithm == "grpo" else
                       {TRAIN_CEILING_VAR: str(a.max_train_cost),
                        TRAIN_MANIFEST_VAR: "<training_manifest_hash from stages/curate.json, known after curate>"})},
            "notes": [f"recorded approved probe ceiling is ${PROBE_CEILING_USD}; a larger value needs new explicit approval",
                      "the inference client stops at its ceiling; rerunning resumes, so a lower ceiling only splits the work",
                      "deploy flags: CRUCIBLE_ENABLE_L4_PROBE=1 (inference), CRUCIBLE_ENABLE_L4_TRAIN=1 (SFT) or "
                      "CRUCIBLE_ENABLE_L4_RL=1 (GRPO) for training"]}


RUNNERS = {"generate": generate, "curate": curate, "audit": audit, "plan": plan, "train": train, "evaluate": evaluate,
           "reenter": reenter}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--iteration-id", required=True)
    ap.add_argument("--root", type=Path, default=Path("checkpoints/loop"))
    ap.add_argument("--env-file")
    ap.add_argument("--algorithm", choices=["sft", "grpo"], default="sft")
    ap.add_argument("--adapter-manifest", type=Path, help="previous iteration's sealed adapter: pins this generation to it")
    ap.add_argument("--taskset", type=Path, default=Path("docs/evaluations/taskset-20261110"))
    ap.add_argument("--seed", type=int, default=20261101)
    ap.add_argument("--population", type=int, default=4)
    ap.add_argument("--tasks", type=int, default=8)
    ap.add_argument("--samples-per-task", type=int, default=1)
    ap.add_argument("--max-train-cost", type=Decimal, default=Decimal("0.50"))
    ap.add_argument("--max-steps", type=int)
    ap.add_argument("--dry-run", action="store_true", help="offline scripted chain: pipeline evidence only, $0")
    ap.add_argument("--plan", action="store_true", help="print per-stage maximum cost and the gate values to set; runs nothing")
    ap.add_argument("--seconds-per-call", type=int, default=120,
                    help="billable seconds bound per model call (default: the client's hard 120 s timeout)")
    ap.add_argument("--eval-seeds", type=int, default=3)
    ap.add_argument("--kill-switch", type=Path, help="file whose existence stops the loop before the next stage "
                                                     "(default <root>/STOP)")
    a = ap.parse_args(argv)
    if not re.match(r"^[a-z0-9][a-z0-9-]{2,40}$", a.iteration_id):
        ap.error("--iteration-id must be lowercase letters, digits and dashes (3-41 chars)")
    if a.dry_run and a.max_steps is None:
        a.max_steps = 2
    if a.plan:
        print(json.dumps(cost_plan(a), indent=1))
        return 0
    if a.env_file:
        from scripts._env import load
        load(a.env_file, set(GATE_VARS + ELASTIC_VARS))
    a.dir = d = a.root / a.iteration_id
    a.kill_switch = a.kill_switch or a.root / "STOP"
    stages = d / "stages"
    stages.mkdir(parents=True, exist_ok=True)
    evidence = DRY_EVIDENCE if a.dry_run else MODEL_EVIDENCE
    done, ran = {}, []
    for name in STAGES:
        path = stages / f"{name}.json"
        prior = json.loads(path.read_text()) if path.is_file() else {}
        if prior.get("status") == "done":
            done[name] = prior
            continue
        if a.kill_switch.exists():  # operator stop: checked before every stage; delete the file and rerun to resume
            print(f"STOPPED before {name}: kill switch {a.kill_switch} exists", file=sys.stderr)
            print(json.dumps({"iteration_id": a.iteration_id, "ran": ran, "stopped_at": name, "status": "killed"}))
            return 4
        try:
            try:
                body = {"stage": name, "status": "done", "evidence": evidence, **RUNNERS[name](a, d, done)}
            except Stop:
                raise
            except Exception as exc:  # class only: messages may carry URLs or credentials
                raise Stop(1, "failed", f"unexpected {type(exc).__name__}") from exc
        except Stop as stop:
            _write(path, {"stage": name, "status": stop.status, "evidence": evidence, **stop.extra})
            if stop.code == 3:
                print(f"BLOCKED at {name}: set {', '.join(stop.extra.get('missing') or ['(see detail)'])} "
                      f"-- {stop.extra['detail']}", file=sys.stderr)
            print(json.dumps({"iteration_id": a.iteration_id, "ran": ran, "stopped_at": name, "status": stop.status}))
            return stop.code
        _write(path, body)
        done[name] = body
        ran.append(name)
    print(json.dumps({"iteration_id": a.iteration_id, "ran": ran, "status": "done", "evidence": evidence,
                      "next_command": done["reenter"]["next_command"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
