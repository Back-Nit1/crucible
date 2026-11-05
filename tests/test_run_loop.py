"""One-command expert-iteration loop, offline: dry-run chain, resume, gates exit 3 with the exact variable names."""
import json

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


def test_grpo_is_a_refusing_stub_until_its_trainer_contract_lands(tmp_path, capsys):
    assert main(["--iteration-id", "it-1", "--root", str(tmp_path), *DRY, "--algorithm", "grpo"]) == 2
    st = status(tmp_path)
    assert st["plan"]["status"] == "done" and st["train"]["status"] == "refused" and "evaluate" not in st


def test_a_dry_run_adapter_never_re_enters_a_real_run(tmp_path, capsys):
    assert main(["--iteration-id", "it-1", "--root", str(tmp_path), *DRY]) == 0
    artifact = status(tmp_path)["train"]["artifact_manifest"]
    assert main(["--iteration-id", "it-2", "--root", str(tmp_path), "--adapter-manifest", artifact]) == 2
    assert status(tmp_path, "it-2")["generate"]["status"] == "refused"
    assert main(["--iteration-id", "it-3", "--root", str(tmp_path), *DRY, "--adapter-manifest", artifact]) == 0  # dry re-entry ok
