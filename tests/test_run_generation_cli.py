"""The single generation CLI, offline (synthetic fixture, in-memory traces): deterministic, resumable, no duplicates."""
import json
from pathlib import Path

import pytest

from scripts.run_generation import load_audited_taskset, main
from eval.taskset import load_tasks, tasks_hash

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


def committed_taskset():
    taskset = Path("docs/evaluations/taskset-20261110")
    return taskset, load_tasks(taskset / "protected.jsonl"), load_tasks(taskset / "reference.jsonl")


def test_taskset_loader_returns_only_audited_reference_tasks():
    taskset, protected, reference = committed_taskset()
    manifests = {t.hard_constraints.category: t.catalog_manifest_hash for t in (*protected, *reference)}
    loaded, audit_hash = load_audited_taskset(taskset, manifests, 1)
    assert loaded == reference[:1] and len(audit_hash) == 64


def test_taskset_loader_refuses_product_leakage(tmp_path):
    _, protected, reference = committed_taskset()
    protected_product = next(t.feasible_set[0] for t in protected if t.feasible_set)
    reference_index = next(i for i, task in enumerate(reference) if task.feasible_set)
    changed = reference[reference_index].model_copy(
        update={"feasible_set": (*reference[reference_index].feasible_set, protected_product)})
    leaked = (*reference[:reference_index], changed, *reference[reference_index + 1:])
    manifests = {t.hard_constraints.category: t.catalog_manifest_hash for t in (*protected, *leaked)}
    taskset = tmp_path / "taskset"
    taskset.mkdir()
    (taskset / "protected.jsonl").write_text("".join(t.model_dump_json() + "\n" for t in protected))
    (taskset / "reference.jsonl").write_text("".join(t.model_dump_json() + "\n" for t in leaked))
    (taskset / "taskset.json").write_text(json.dumps({
        "protected_hash": tasks_hash(protected), "reference_hash": tasks_hash(leaked),
    }))
    with pytest.raises(ValueError, match="product_overlap"):
        load_audited_taskset(taskset, manifests, 1)
