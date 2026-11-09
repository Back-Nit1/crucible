"""/models/live: probe files and running-evaluation progress, read from disk, whitelisted fields only."""
import json

from fastapi.testclient import TestClient

import api.main as main


def test_models_live_reports_probes_and_evaluation_progress(tmp_path, monkeypatch):
    docs = tmp_path / "docs" / "run"
    docs.mkdir(parents=True)
    (docs / "probe.json").write_text(json.dumps({
        "experiment": "qwen-bounded-probe", "status": "passed", "finished_at": "2026-11-08T10:00:00+00:00",
        "model": {"checkpoint": "qwen-base", "id": "Qwen/x"}, "records": [{"raw": "secret model text"}],
        "metrics": {"valid_structured_call": {"value": 1.0, "numerator": 20, "denominator": 20},
                    "cost_usd": {"total": "0.03", "known": True}, "latency_ms": {"p50": 5100.0}}}))
    (docs / "probe_other.json").write_text(json.dumps({"experiment": "something-else"}))
    (docs / "broken_probe.json").write_text("{not json")
    ev = tmp_path / "evals" / "eval-1"
    (ev / "episodes" / "base").mkdir(parents=True)
    (ev / "manifest.json").write_text(json.dumps({"tasks": [{}, {}], "seeds": [1, 2], "contenders": [{"id": "base", "kind": "base"}, {"id": "memory", "kind": "memory"}]}))
    for i, killed in enumerate((False, True, False)):
        (ev / "episodes" / "base" / f"t{i}__1.json").write_text(json.dumps({"episode": {"killed": killed, "cost": "0.01"}}))
    monkeypatch.setattr(main, "REPO_ROOT", tmp_path)
    monkeypatch.setenv("CRUCIBLE_EVAL_ROOT", str(tmp_path / "evals"))

    body = TestClient(main.create_app()).get("/models/live").json()
    assert [p["id"] for p in body["probes"]] == ["docs/run/probe.json"]
    probe = body["probes"][0]
    assert probe["rates"]["valid_structured_call"] == {"value": 1.0, "numerator": 20, "denominator": 20}
    assert probe["cost_usd"] == "0.03" and "secret" not in json.dumps(body)
    (row_base, row_memory), = [e["contenders"] for e in body["evaluations"]]
    assert row_base == {"contender": "base", "kind": "base", "done": 3, "expected": 4, "killed": 1, "cost_usd": "0.03"}
    assert row_memory["done"] == 0 and body["evaluations"][0]["status"] == "running"
