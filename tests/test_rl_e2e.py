"""Offline GRPO end to end — PIPELINE EVIDENCE ONLY, never a model-quality result:
scripted world generation (K samples per task, oracle shopper) -> rollouts.jsonl -> train_lora --algorithm grpo --plan-only
--allow-scripted-traces -> the sealed shard -> real PEFT backend on a tiny random Qwen2 (CPU), interrupted and resumed ->
sealed artifact -> scripts.inspect_training_artifact. Skipped like tests/test_training_torch_backend.py without torch."""
import json
from pathlib import Path

from tests.test_training_torch_backend import NOW, tiny_model_dir  # noqa: F401  (fixture; module skips without torch)
from tests.test_rl_torch import GRPO_HP  # noqa: E402
from modal_app.adapter_artifact import load_manifest  # noqa: E402
from scripts.inspect_training_artifact import main as inspect_main  # noqa: E402
from scripts.run_generation import main as run_generation  # noqa: E402
from scripts.train_lora import main as train_lora  # noqa: E402
from training.planning import LoRAHyperparameters, LoRAPlan, plan_hash  # noqa: E402
from training.resume import CheckpointStore, RunIdentity  # noqa: E402
from training.shard import GRPO_FORMAT, parse_shard  # noqa: E402
from training.torch_backend import TorchLoraBackend, backend_signature, load_base_model  # noqa: E402
from training.trainer import run_training  # noqa: E402


def generate(tmp: Path) -> Path:
    assert run_generation(["--provider", "synthetic", "--traces", "memory", "--model", "scripted", "--memory", "off",
                           "--seed", "20261105", "--population", "4", "--tasks", "4", "--samples-per-task", "2",
                           "--iteration-id", "it-e2e", "--generation-id", "grpo-e2e",
                           "--checkpoint-dir", str(tmp / "ckpt"), "--out-dir", str(tmp / "runs")]) == 0
    return tmp / "runs" / "grpo-e2e" / "rollouts.jsonl"


def test_scripted_rollouts_to_a_sealed_grpo_adapter_on_the_real_backend(tiny_model_dir, tmp_path, capsys):
    rollouts = generate(tmp_path)
    plan_dir = tmp_path / "plan"
    assert train_lora(["--algorithm", "grpo", "--rollouts", str(rollouts), "--run-id", "grpo-e2e", "--max-cost", "0.5",
                       "--max-steps", "2", "--out", str(plan_dir), "--plan-only", "--write-shard"]) == 2  # refused without the flag
    assert train_lora(["--algorithm", "grpo", "--rollouts", str(rollouts), "--run-id", "grpo-e2e", "--max-cost", "0.5",
                       "--max-steps", "2", "--out", str(plan_dir), "--plan-only", "--write-shard", "--allow-scripted-traces"]) == 0
    planned = json.loads((plan_dir / "training_plan.json").read_text())
    assert planned["status"] == "planned" and planned["training_data_source"] == "scripted-v1" and planned["rl"]["stats"]["rows"] > 0
    sh = parse_shard((plan_dir / "dataset.jsonl").read_bytes(), expected_dataset_hash=planned["dataset_hash"],
                     expected_manifest_hash=planned["training_manifest_hash"])
    assert sh.format == GRPO_FORMAT and len(sh.examples) == planned["record_count"]

    # Same rollout set, same GRPO knobs; LoRA shape and base swapped for the tiny CPU model (recorded honestly below).
    hp = LoRAHyperparameters(**{**GRPO_HP.model_dump(), "grpo": LoRAHyperparameters.model_validate(planned["hyperparameters"]).grpo,
                                "max_steps": 2, "gradient_accumulation_steps": 1})
    plan = LoRAPlan(base_model="tiny/qwen2-random", base_revision="0" * 40, training_manifest_hash=planned["training_manifest_hash"],
                    record_count=len(sh.examples), gpu="cpu", hyperparameters=hp, maximum_approved_cost=planned["maximum_approved_cost_usd"])
    identity = RunIdentity(run_id="grpo-e2e", plan_hash=plan_hash(plan), base_model=plan.base_model, base_revision=plan.base_revision,
                           training_manifest_hash=plan.training_manifest_hash, dataset_hash=sh.dataset_hash,
                           data_source_model_version=sh.source_model_version, hyperparameters=hp.model_dump(mode="json"),
                           backend_signature=backend_signature())

    def launch(stop=None):
        model, tok = load_base_model(tiny_model_dir, hp, device="cpu", require_cuda_for_large=False)
        backend = TorchLoraBackend(model=model, tokenizer=tok, shard=sh, hp=hp, total_steps=hp.total_steps(len(sh.examples)), device="cpu")
        store = CheckpointStore(tmp_path / "volume", identity, clock=lambda: NOW)
        return run_training(store=store, identity=identity, backend=backend, hp=hp, record_count=len(sh.examples),
                            total_budget_seconds=600, gpu="cpu-test", clock=lambda: NOW, stop_after_steps=stop), store

    paused, _ = launch(stop=1)
    final, store = launch()
    assert paused.status == "paused" and final.status == "final" and final.resumed_from_step == 1
    assert all(abs(x) < float("inf") for x in final.losses)
    manifest_path = store.final_dir / "artifact_manifest.json"
    m = load_manifest(manifest_path)
    assert m.data_source_model_version == "scripted-v1" and m.hyperparameters["method"] == "lora_grpo"
    assert m.training_manifest_hash == planned["rl"]["rollout_set_hash"] and m.checkpoint_id.startswith("qwen-lora-")
    capsys.readouterr()
    assert inspect_main([str(manifest_path), "--adapter-dir", str(store.final_dir)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["verified"] is True and report["adapter_files_checked"] is True
    print(json.dumps({"evidence": "pipeline only (scripted oracle rollouts, tiny random Qwen2, CPU)", "plan_stats": planned["rl"]["stats"],
                      "rollout_set_hash": m.training_manifest_hash, "dataset_hash": m.dataset_hash, "checkpoint_id": m.checkpoint_id,
                      "losses": final.losses, "launches": len(m.segments)}))
