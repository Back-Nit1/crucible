"""The single generation CLI, offline (synthetic fixture, in-memory traces): deterministic, resumable, no duplicates."""
import json

import pytest

from scripts.run_generation import main

ARGS = ["--provider", "synthetic", "--traces", "memory", "--seed", "5", "--population", "8", "--tasks", "6"]


def run(tmp_path, tag, *extra):
    return main([*ARGS, "--checkpoint-dir", str(tmp_path / f"ck-{tag}"), "--out-dir", str(tmp_path / f"out-{tag}"), *extra])


def test_fixture_generation_is_deterministic_and_labelled_scripted(tmp_path, capsys):
    assert run(tmp_path, "a") == 0 and run(tmp_path, "b") == 0
    gen = "gen-5-p8-t6"
    a, b = (json.loads((tmp_path / f"out-{t}" / gen / "summary.json").read_text()) for t in "ab")
    assert a == b and a["policy"] == "scripted-v1" and "pipeline evidence" in a["note"]
    assert a["params"]["provider"] == "synthetic" and a["params"]["payments"] == "mock"
    assert a["episodes"]["completed"] == a["episodes"]["traced"] == 48
    assert (tmp_path / f"out-a" / gen / "summary.md").read_text() == (tmp_path / f"out-b" / gen / "summary.md").read_text()


def test_interrupt_then_rerun_resumes_without_duplicates(tmp_path, capsys):
    assert run(tmp_path, "r", "--interrupt-after", "20") == 0
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["status"] == "interrupted"
    assert run(tmp_path, "r") == 0
    out = capsys.readouterr().out
    assert json.loads(out[out.index("{"):])["executed_this_run"] == 28


def test_qwen_requires_gpu_launch_authorization(tmp_path, monkeypatch):
    for k in ("CRUCIBLE_MODAL_TOKEN_ROTATED", "CRUCIBLE_MODAL_BILLING_CONFIRMED", "CRUCIBLE_MODAL_APPROVED_CEILING_USD"):
        monkeypatch.delenv(k, raising=False)
    from agents.model import InferenceError
    with pytest.raises(InferenceError, match="gpu_launch_not_authorized"):
        run(tmp_path, "q", "--model", "qwen")
