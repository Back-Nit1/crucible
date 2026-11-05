import json

import pytest

from modal_app.train_protocol import TrainRequest
from scripts.inspect_training_artifact import main as inspect_main
from scripts.train_lora import main
from tasks.schemas import TaskSplit
from tests.test_training_dataset import curated, rebuilt
from tests.test_training_gates import ENV
from tests.test_training_service import Backend, NOW
from training.gates import TRAIN_CEILING_VAR, TRAIN_MANIFEST_VAR
from training.service import execute


@pytest.fixture
def files(tmp_path):
    records, manifest = curated()
    many = tuple(records[0].model_copy(update={"source_episode_id": f"ep-{i}", "messages": (
        {"role": "user", "content": f"need shoes {i}"}, *records[0].messages[1:])}) for i in range(4))
    manifest = rebuilt(many, manifest)
    rec = tmp_path / "sft.jsonl"
    rec.write_text("".join(r.model_dump_json() + "\n" for r in many))
    man = tmp_path / "training_manifest.json"
    man.write_text(manifest.model_dump_json())
    return rec, man, manifest, tmp_path


def argv(files, *extra, mode="--plan-only", cost="0.5"):
    rec, man, _, tmp = files
    return ["--records", str(rec), "--manifest", str(man), "--run-id", "run-smoke", "--max-cost", cost, "--out", str(tmp / "out"),
            "--allow-scripted-traces", mode, *extra]


def set_env(monkeypatch, manifest_hash, **over):
    for k, v in {**ENV, TRAIN_MANIFEST_VAR: manifest_hash, **over}.items():
        monkeypatch.setenv(k, v)


def clear_env(monkeypatch):
    for k in ("CRUCIBLE_MODAL_TOKEN_ROTATED", "CRUCIBLE_MODAL_BILLING_CONFIRMED", TRAIN_CEILING_VAR, TRAIN_MANIFEST_VAR):
        monkeypatch.delenv(k, raising=False)


def fake_transport(root, backend=None):
    backend = backend or Backend()
    return lambda payload: execute(TrainRequest.model_validate(payload), runs_root=root, backend_factory=lambda s, h, n: backend,
                                   signature="fake", clock=lambda: NOW).model_dump(mode="json")


def read(files, name):
    return json.loads((files[3] / "out" / name).read_text())


def test_plan_only_writes_a_planned_record_that_never_says_trained(files, capsys, monkeypatch):
    clear_env(monkeypatch)
    assert main(argv(files)) == 0
    plan = read(files, "training_plan.json")
    assert plan["status"] == "planned" and plan["trained"] is False and "nothing ran" in plan["note"]
    assert plan["training_manifest_hash"] == files[2].content_hash and plan["record_count"] == 4 and plan["budget_seconds_at_list_rates"] > 0
    assert any("modal deploy" in c for c in plan["launch_commands"]) and not (files[3] / "out" / "artifact_manifest.json").exists()
    assert not (files[3] / "out" / "dataset.jsonl").exists()  # raw training data only on --write-shard


def test_scripted_oracle_traces_are_refused_without_the_explicit_flag(files, capsys):
    rec, man, manifest, tmp = files
    man.write_text(manifest.model_copy(update={"model_version": "scripted-v1"}).model_dump_json())
    base = ["--records", str(rec), "--manifest", str(man), "--run-id", "run-smoke", "--max-cost", "0.5", "--plan-only", "--out", str(tmp / "o")]
    assert main(base) == 2 and "scripted" in capsys.readouterr().out
    assert main([*base, "--allow-scripted-traces"]) == 0


def test_launch_without_authorization_is_blocked_with_zero_spend_and_calls_nothing(files, monkeypatch):
    clear_env(monkeypatch)
    called = []
    assert main(argv(files, mode="--launch"), transport=lambda p: called.append(p)) == 3
    run = read(files, "training_run.json")
    assert run["status"] == "blocked_not_run" and run["trained"] is False and run["gpu_spend_usd"] == "0" and not called
    assert TRAIN_MANIFEST_VAR in run["blocker"]


def test_launch_runs_split_leakage_audit_before_transport(files, capsys):
    rec, man, manifest, _ = files
    leaked = manifest.model_copy(update={
        "source_task_splits": {episode_id: TaskSplit.TEST for episode_id in manifest.source_episode_ids},
    })
    man.write_text(leaked.model_dump_json())
    called = []
    assert main(argv(files, mode="--launch"), transport=lambda payload: called.append(payload)) == 2
    assert "split_leakage" in capsys.readouterr().out and not called


def test_launch_for_a_different_manifest_hash_is_blocked(files, monkeypatch):
    set_env(monkeypatch, "f" * 64)
    assert main(argv(files, mode="--launch"), transport=lambda p: pytest.fail("must not call")) == 3
    assert "approved_manifest_mismatch" in read(files, "training_run.json")["blocker"]


def test_authorized_launch_pauses_then_resumes_to_a_trained_verified_artifact(files, monkeypatch, capsys):
    set_env(monkeypatch, files[2].content_hash)
    root = files[3] / "volume"
    transport = fake_transport(root)
    assert main(argv(files, "--epochs", "3", "--max-steps", "3", "--stop-after-steps", "1", mode="--launch"), transport=transport) == 0
    paused = read(files, "training_run.json")
    assert paused["status"] == "paused" and paused["trained"] is False and not (files[3] / "out" / "artifact_manifest.json").exists()
    assert main(argv(files, "--epochs", "3", "--max-steps", "3", mode="--launch"), transport=transport, now=lambda: NOW) == 0
    done = read(files, "training_run.json")
    assert done["status"] == "trained" and done["trained"] is True and done["checkpoint_id"].startswith("qwen-lora-")
    assert done["artifact_ref"].startswith("modal-volume://crucible-qwen-adapters/runs/run-smoke/final@")
    assert done["cost_usd"] is not None and "estimate" in done["cost_basis"]
    ref = read(files, "adapter_ref.json")
    assert ref["adapter_ref"] == done["artifact_ref"] and ref["adapter_sha256"] == done["adapter_hash"]
    assert ref["checkpoint_id"] == "qwen-lora-" + ref["adapter_sha256"][:12] and ref["training_manifest_hash"] == files[2].content_hash
    assert (ref["base_model"], len(ref["base_revision"])) == ("Qwen/Qwen2.5-7B-Instruct", 40)
    assert inspect_main([str(files[3] / "out" / "artifact_manifest.json"), "--adapter-dir", str(root / "run-smoke" / "final")]) == 0
    assert '"verified": true' in capsys.readouterr().out


def test_transport_failure_is_reported_without_message_text(files, monkeypatch):
    set_env(monkeypatch, files[2].content_hash)

    def boom(payload):
        raise ConnectionError("https://secret.example/token=abc")

    assert main(argv(files, mode="--launch"), transport=boom) == 1
    run = read(files, "training_run.json")
    assert run["status"] == "failed" and run["trained"] is False and "secret" not in json.dumps(run)


def test_a_server_response_for_a_different_run_is_not_accepted_as_trained(files, monkeypatch):
    set_env(monkeypatch, files[2].content_hash)
    root = files[3] / "volume"
    good = fake_transport(root)
    assert main(argv(files, "--epochs", "2", "--max-steps", "2", mode="--launch"), transport=good) == 0
    tampered = lambda payload: {**good(payload), "manifest": {**good(payload)["manifest"], "dataset_hash": "0" * 64}}
    assert main(argv(files, "--epochs", "2", "--max-steps", "2", mode="--launch"), transport=tampered) == 1
    assert read(files, "training_run.json")["status"] == "failed"


def test_inspect_rejects_tampered_manifest_and_adapter(files, monkeypatch, capsys):
    set_env(monkeypatch, files[2].content_hash)
    root = files[3] / "volume"
    assert main(argv(files, "--epochs", "2", "--max-steps", "2", mode="--launch"), transport=fake_transport(root)) == 0
    path = files[3] / "out" / "artifact_manifest.json"
    adapter = root / "run-smoke" / "final"
    (adapter / "adapter_model.safetensors").write_text("evil")
    capsys.readouterr()
    assert inspect_main([str(path), "--adapter-dir", str(adapter)]) == 1
    assert "adapter_content_mismatch" in capsys.readouterr().out
    path.write_text(path.read_text().replace('"gpu": "L4"', '"gpu": "H100"'))
    assert inspect_main([str(path)]) == 1


# --- GRPO: same CLI, --algorithm grpo --------------------------------------------------------------------------------
from tests.test_rl_dataset import group  # noqa: E402
from training.gates import RL_CEILING_VAR, RL_ROLLOUTS_VAR  # noqa: E402


@pytest.fixture
def rollouts_file(tmp_path):
    path = tmp_path / "rollouts.jsonl"
    protected = [r.model_copy(update={"split": TaskSplit.TEST, "episode_id": "p-" + r.episode_id, "group_id": "c" * 64}) for r in group()]
    path.write_text("".join(r.model_dump_json() + "\n"
                            for r in group() + group("t-2", "b" * 64, (D("0.1"), D("0.4"), D("0.7"))) + protected))
    return path, tmp_path


from decimal import Decimal as D  # noqa: E402


def grpo_argv(rf, *extra, mode="--plan-only", cost="0.5"):
    path, tmp = rf
    return ["--algorithm", "grpo", "--rollouts", str(path), "--run-id", "run-grpo", "--max-cost", cost, "--out", str(tmp / "out"),
            mode, *extra]


def grpo_transport(root):
    backend = Backend()
    return lambda payload: execute(TrainRequest.model_validate(payload), runs_root=root, backend_factory=lambda s, h, n: backend,
                                   signature="fake", clock=lambda: NOW, algorithms=frozenset({"grpo"})).model_dump(mode="json")


def test_grpo_plan_only_prints_cost_and_the_exact_rl_gates(rollouts_file, monkeypatch, capsys):
    clear_env(monkeypatch)
    assert main(grpo_argv(rollouts_file, "--kl-beta", "0.1")) == 0
    plan = json.loads((rollouts_file[1] / "out" / "training_plan.json").read_text())
    assert plan["status"] == "planned" and plan["trained"] is False and plan["algorithm"] == "grpo"
    assert plan["hyperparameters"]["method"] == "qlora_grpo" and plan["hyperparameters"]["grpo"]["kl_beta"] == "0.1"
    assert plan["rl"]["stats"]["rollouts"] == 5 and plan["rl"]["stats"]["groups"] == 2 and plan["record_count"] == 4  # zero-advantage middle sample dropped
    cost = plan["rl"]["cost"]
    assert plan["rl"]["stats"]["excluded_protected_split"] == 2
    assert cost["rollout_inference"]["max_model_calls"] == 5 * 20 * 4  # episodes x steps x runner x adapter tries
    assert cost["rollout_inference"]["episodes"] == 5 and D(cost["max_cost_usd"]) == \
        D(cost["rollout_inference"]["max_cost_usd"]) + D(cost["update"]["max_cost_usd"])
    env = plan["rl"]["env"]
    assert env[RL_ROLLOUTS_VAR] == plan["training_manifest_hash"] == plan["rl"]["rollout_set_hash"]
    assert env[RL_CEILING_VAR] == "0.5" and env["CRUCIBLE_MODAL_TOKEN_ROTATED"] == "1"
    assert any("CRUCIBLE_ENABLE_L4_RL=1" in c for c in plan["launch_commands"])
    assert (rollouts_file[1] / "out" / "rollout_manifest.json").exists()  # what the leakage audit checked


def test_grpo_refuses_scripted_rollouts_without_the_flag(rollouts_file, capsys):
    path, _ = rollouts_file
    path.write_text("".join(r.model_copy(update={"scripted": True}).model_dump_json() + "\n" for r in group()))
    assert main(grpo_argv(rollouts_file)) == 2 and "scripted_traces" in capsys.readouterr().out
    assert main(grpo_argv(rollouts_file, "--allow-scripted-traces")) == 0


def test_grpo_runs_the_leakage_audit_on_the_rollouts(rollouts_file, capsys):
    path, _ = rollouts_file
    leaked = [r.model_copy(update={"episode_id": f"gen:{r.episode_id}:batch-20261110-0002"}) for r in group()]
    path.write_text("".join(r.model_dump_json() + "\n" for r in leaked))
    assert main(grpo_argv(rollouts_file)) == 2 and "split_leakage" in capsys.readouterr().out


def test_grpo_launch_needs_rl_gates_then_trains_a_verified_grpo_artifact(rollouts_file, monkeypatch, capsys):
    clear_env(monkeypatch)
    set_env(monkeypatch, "e" * 64)  # SFT approval only: must not unlock GRPO
    assert main(grpo_argv(rollouts_file, mode="--launch"), transport=lambda p: pytest.fail("must not call")) == 3
    blocked = json.loads((rollouts_file[1] / "out" / "training_run.json").read_text())
    assert blocked["status"] == "blocked_not_run" and RL_ROLLOUTS_VAR in blocked["blocker"]
    rollout_hash = blocked["training_manifest_hash"]
    monkeypatch.setenv(RL_CEILING_VAR, "0.5")
    monkeypatch.setenv(RL_ROLLOUTS_VAR, rollout_hash)
    root = rollouts_file[1] / "volume"
    assert main(grpo_argv(rollouts_file, "--max-steps", "2", mode="--launch"), transport=grpo_transport(root), now=lambda: NOW) == 0
    done = json.loads((rollouts_file[1] / "out" / "training_run.json").read_text())
    assert done["status"] == "trained" and done["checkpoint_id"].startswith("qwen-lora-") and done["algorithm"] == "grpo"
    art = json.loads((rollouts_file[1] / "out" / "artifact_manifest.json").read_text())
    assert art["hyperparameters"]["method"] == "qlora_grpo" and art["training_manifest_hash"] == rollout_hash
    assert inspect_main([str(rollouts_file[1] / "out" / "artifact_manifest.json"), "--adapter-dir", str(root / "run-grpo" / "final")]) == 0


def test_grpo_policy_adapter_manifest_pins_the_update_to_that_checkpoint(rollouts_file, monkeypatch, capsys):
    path, tmp = rollouts_file
    other = tmp / "prev.json"
    # a real sealed manifest from an SFT run is a valid policy checkpoint; base rollouts are then stale for it
    clear_env(monkeypatch)
    from tests.test_adapter_artifact import manifest as sealed
    m = sealed(tmp / "prev")
    other.write_text(m.model_dump_json())
    assert main(grpo_argv(rollouts_file, "--policy-adapter-manifest", str(other))) == 2
    assert "stale_rollouts" in capsys.readouterr().out
    path.write_text("".join(r.model_copy(update={"model_checkpoint": m.checkpoint_id, "adapter_hash": m.adapter_hash}).model_dump_json()
                            + "\n" for r in group()))
    assert main(grpo_argv(rollouts_file, "--policy-adapter-manifest", str(other))) == 0
    plan = json.loads((tmp / "out" / "training_plan.json").read_text())
    assert plan["hyperparameters"]["grpo"]["policy_adapter_hash"] == m.adapter_hash
