import json
from pathlib import Path

import pytest

from modal_app.train_protocol import TrainRequest
from scripts.inspect_training_artifact import main as inspect_main
from scripts.train_lora import main
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
