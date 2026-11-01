"""CLI plumbing: plan refuses leaking sets, run is BLOCKED (and calls nothing) without authorization."""
import pytest

from catalog.providers.elastic import load_manifest_hashes
from scripts import build_eval_taskset, run_evaluation


def test_plan_run_blocked_and_report_refusal(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("CRUCIBLE_MODAL_TOKEN_ROTATED", raising=False)
    monkeypatch.delenv("CRUCIBLE_MODAL_APPROVED_CEILING_USD", raising=False)
    ts = tmp_path / "ts"
    # real category hashes are required by plan's catalog/manifest check: build the synthetic set against them
    real = load_manifest_hashes()
    from tests.fixtures import eval_catalog as fx
    cats = sorted(real)
    monkeypatch.setattr(fx, "CATEGORIES", tuple(cats[:3]), raising=False)
    monkeypatch.setattr(fx, "HASHES", {c: real[c] for c in cats[:3]})
    assert build_eval_taskset.main(["--provider", "synthetic", "--out-dir", str(ts), "--size", "60", "--held-out", cats[2]]) == 0
    root = str(tmp_path / "root")
    assert run_evaluation.main(["plan", "--evaluation-id", "e1", "--root", root, "--taskset", str(ts), "--seeds", "1,2"]) == 0
    with pytest.raises(SystemExit) as blocked:
        run_evaluation.main(["run", "--evaluation-id", "e1", "--root", root])                   # no authorization -> nothing runs
    assert blocked.value.code == 3
    assert not list((tmp_path / "root" / "e1").glob("episodes/*/*.json"))
    with pytest.raises(Exception, match="expected"):
        run_evaluation.main(["report", "--evaluation-id", "e1", "--root", root])                # nothing to finalize
