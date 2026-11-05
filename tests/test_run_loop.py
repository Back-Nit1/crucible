"""One-command expert-iteration loop, offline: dry-run chain, resume, gates exit 3 with the exact variable names."""
import json
from decimal import Decimal

import pytest

from scripts.run_loop import GATE_VARS, STAGES, main

DRY = ["--dry-run", "--population", "6", "--tasks", "4", "--seed", "5"]


@pytest.fixture(autouse=True)
def no_gates(monkeypatch):
    for k in GATE_VARS:
        monkeypatch.delenv(k, raising=False)


def status(root, it="it-1"):
    return {s: json.loads((root / it / "stages" / f"{s}.json").read_text()) for s in STAGES
            if (root / it / "stages" / f"{s}.json").exists()}


def test_dry_run_runs_the_whole_chain_offline_and_is_labelled_pipeline_evidence(tmp_path, capsys):
    assert main(["--iteration-id", "it-1", "--root", str(tmp_path), *DRY]) == 0
    st = status(tmp_path)
    assert list(st) == list(STAGES) and all(s["status"] == "done" for s in st.values())
    assert all(s["evidence"] == "pipeline_evidence_scripted_dry_run" for s in st.values())
    assert st["generate"]["rollouts"] > 0 and st["curate"]["records"] > 0
    assert st["train"]["adapter_hash"] and st["reenter"]["checkpoint"].startswith("qwen-lora-")
    assert "--adapter-manifest" in st["reenter"]["next_command"]
    assert st["evaluate"]["contenders"] == ["base-qwen", "sft-" + st["train"]["adapter_hash"][:12]]
    capsys.readouterr()
    assert main(["--iteration-id", "it-1", "--root", str(tmp_path), *DRY]) == 0  # rerun: everything already done
    assert json.loads(capsys.readouterr().out)["ran"] == []


def test_rerun_resumes_at_the_first_unfinished_stage(tmp_path, capsys):
    assert main(["--iteration-id", "it-1", "--root", str(tmp_path), *DRY]) == 0
    for s in ("evaluate", "reenter"):
        (tmp_path / "it-1" / "stages" / f"{s}.json").unlink()
    capsys.readouterr()
    assert main(["--iteration-id", "it-1", "--root", str(tmp_path), *DRY]) == 0
    assert json.loads(capsys.readouterr().out)["ran"] == ["evaluate", "reenter"]


def test_real_run_without_gates_stops_at_generation_with_exit_3_and_names_the_variables(tmp_path, capsys):
    assert main(["--iteration-id", "it-1", "--root", str(tmp_path)]) == 3
    out = capsys.readouterr()
    for name in ("CRUCIBLE_MODAL_TOKEN_ROTATED", "CRUCIBLE_MODAL_BILLING_CONFIRMED", "CRUCIBLE_MODAL_APPROVED_CEILING_USD"):
        assert name in out.err
    st = status(tmp_path)
    assert list(st) == ["generate"] and st["generate"]["status"] == "blocked"
    assert "CRUCIBLE_MODAL_APPROVED_CEILING_USD" in st["generate"]["missing"]


def test_a_dry_run_adapter_never_re_enters_a_real_run(tmp_path, capsys):
    assert main(["--iteration-id", "it-1", "--root", str(tmp_path), *DRY]) == 0
    artifact = status(tmp_path)["train"]["artifact_manifest"]
    assert main(["--iteration-id", "it-2", "--root", str(tmp_path), "--adapter-manifest", artifact]) == 2
    assert status(tmp_path, "it-2")["generate"]["status"] == "refused"
    assert main(["--iteration-id", "it-3", "--root", str(tmp_path), *DRY, "--adapter-manifest", artifact]) == 0  # dry re-entry ok


def test_plan_prints_per_stage_max_cost_and_the_exact_gate_values(tmp_path, capsys):
    from training.gates import cost_per_second, list_rates
    assert main(["--iteration-id", "it-1", "--root", str(tmp_path), "--plan", "--population", "2", "--tasks", "3",
                 "--max-train-cost", "0.40"]) == 0
    p = json.loads(capsys.readouterr().out)
    rate = cost_per_second(list_rates())
    gen = p["stages"]["generate"]
    assert gen["max_model_calls"] == 2 * 3 * 20 * 4 and gen["seconds_per_call"] == 120  # episodes x steps x runner x adapter tries
    assert gen["max_seconds_per_episode"] == 900 + 4 * 120 and gen["max_seconds"] == 6 * 1380 + 60  # cap + the step in flight
    assert gen["max_cost_usd"] == str((gen["max_seconds"] * rate).quantize(Decimal("0.000001")))
    assert Decimal(p["stages"]["train"]["max_cost_usd"]) <= Decimal("0.40") and p["stages"]["train"]["budget_seconds"] > 0
    assert p["stages"]["curate"]["max_cost_usd"] == "0"
    env = p["env"]
    assert env["CRUCIBLE_MODAL_TOKEN_ROTATED"] == "1" and env["CRUCIBLE_MODAL_TRAINING_CEILING_USD"] == "0.40"
    assert env["CRUCIBLE_MODAL_APPROVED_CEILING_USD"] == max(gen["max_cost_usd"], p["stages"]["evaluate"]["max_cost_per_client_usd"],
                                                             key=Decimal)
    assert "after curate" in env["CRUCIBLE_MODAL_TRAINING_APPROVED_MANIFEST_HASH"]
    assert p["cold_start_seconds"] is None and not (tmp_path / "it-1").exists()  # planning runs nothing, writes nothing


def test_kill_switch_file_stops_the_loop_between_stages(tmp_path, capsys):
    (tmp_path / "STOP").write_text("operator stop")
    assert main(["--iteration-id", "it-1", "--root", str(tmp_path), *DRY]) == 4
    assert status(tmp_path) == {} and "STOP" in capsys.readouterr().err
    (tmp_path / "STOP").unlink()
    assert main(["--iteration-id", "it-1", "--root", str(tmp_path), *DRY]) == 0


def test_loop_status_endpoint_is_read_only_and_leaks_no_paths(tmp_path, monkeypatch, capsys):
    from tests.test_api_endpoints import client
    assert main(["--iteration-id", "it-1", "--root", str(tmp_path), *DRY]) == 0
    assert main(["--iteration-id", "it-2", "--root", str(tmp_path)]) == 3  # real run blocked at the inference gate
    (tmp_path / "it-3" / "stages").mkdir(parents=True)
    (tmp_path / "it-3" / "stages" / "generate.json").write_text("{half-written")
    monkeypatch.setenv("CRUCIBLE_LOOP_ROOT", str(tmp_path))
    before = sorted(p.read_bytes() for p in tmp_path.rglob("stages/*.json"))
    r = client().get("/loop/status")
    assert r.status_code == 200
    body = r.json()
    its = {i["iteration_id"]: i for i in body["iterations"]}
    assert [s["stage"] for s in its["it-1"]["stages"]] == list(STAGES) and its["it-1"]["next_stage"] is None
    assert its["it-2"]["next_stage"] == "generate" and its["it-2"]["stages"][0]["status"] == "blocked"
    assert "CRUCIBLE_MODAL_APPROVED_CEILING_USD" in its["it-2"]["stages"][0]["missing"]
    assert its["it-3"]["stages"] == [{"stage": "generate", "status": "unreadable"}]
    assert str(tmp_path) not in r.text and body["kill_switch"] is False
    assert sorted(p.read_bytes() for p in tmp_path.rglob("stages/*.json")) == before


def test_grpo_dry_run_end_to_end(tmp_path, capsys):
    assert main(["--iteration-id", "it-g", "--root", str(tmp_path), *DRY, "--algorithm", "grpo", "--samples-per-task", "2"]) == 0
    st = status(tmp_path, "it-g")
    assert all(s["status"] == "done" for s in st.values()) and st["plan"]["rollout_set_hash"]
    assert "CRUCIBLE_MODAL_RL_CEILING_USD" in st["plan"]["gate_env"]
    artifact = json.loads((tmp_path / "it-g" / "train" / "artifact_manifest.json").read_text())
    assert artifact["hyperparameters"]["method"] == "qlora_grpo"
    assert st["evaluate"]["contenders"] == ["base-qwen", "grpo-" + st["train"]["adapter_hash"][:12]]


def test_grpo_plan_names_the_rl_gate_variables(tmp_path, capsys):
    assert main(["--iteration-id", "it-2", "--root", str(tmp_path), "--plan", "--algorithm", "grpo"]) == 0
    env = json.loads(capsys.readouterr().out)["env"]
    assert "CRUCIBLE_MODAL_RL_CEILING_USD" in env and "rollout_set_hash" in env["CRUCIBLE_MODAL_RL_APPROVED_ROLLOUTS_HASH"]
    assert "CRUCIBLE_MODAL_TRAINING_CEILING_USD" not in env


def test_stage_errors_are_recorded_not_raised(tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace

    import scripts.run_generation
    import scripts.run_loop as loop
    import scripts.train_lora
    from world.runtime import ModelUnavailable

    def down(argv):
        raise ModelUnavailable("3 consecutive model failures")
    with monkeypatch.context() as m:
        m.setattr(scripts.run_generation, "main", down)
        assert main(["--iteration-id", "it-1", "--root", str(tmp_path), *DRY]) == 0  # paused: a rerun resumes
    assert status(tmp_path)["generate"]["status"] == "paused"
    with monkeypatch.context() as m:
        m.setattr(loop, "_dry_train", lambda *x: {}["missing"])
        assert main(["--iteration-id", "it-1", "--root", str(tmp_path), *DRY]) == 1
    assert status(tmp_path)["train"]["status"] == "failed" and status(tmp_path)["train"]["detail"] == "unexpected KeyError"
    # a refused launch writes no training_run.json: the stage is refused, not a FileNotFoundError
    monkeypatch.setattr(scripts.train_lora, "main", lambda argv: 2)
    a = SimpleNamespace(dry_run=False, env_file=None, algorithm="sft", taskset=tmp_path, iteration_id="it-9",
                        max_train_cost="0.5", dir=tmp_path / "it-9", max_steps=None, adapter_manifest=None)
    with pytest.raises(loop.Stop) as stop:
        loop.train(a, tmp_path / "it-9", {"generate": {"generation_dir": str(tmp_path)}, "plan": {}})
    assert stop.value.status == "refused"


def test_next_command_keeps_the_iteration_settings_and_increments_the_id(tmp_path, capsys):
    assert main(["--iteration-id", "it-1", "--root", str(tmp_path), *DRY, "--samples-per-task", "2"]) == 0
    nxt = status(tmp_path)["reenter"]["next_command"]
    assert "--iteration-id it-2 " in nxt and "--samples-per-task 2" in nxt and "--algorithm sft" in nxt
