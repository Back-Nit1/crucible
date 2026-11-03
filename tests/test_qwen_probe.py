import datetime as dt
import json
from decimal import Decimal

import pytest

import scripts.qwen_probe as probe
from agents.model import QwenInferenceResponse, QwenModelAdapter
from agents.qwen_client import ModalQwenClient
from modal_app.qwen_toolcalls import MODEL_ID, MODEL_REVISION, prompt_manifest
from scripts.qwen_probe import PASS_BAR, THRESHOLDS, blocked_report, main, run_probe, write

CALL = '<tool_call>{"name": "parse_intent", "arguments": {"raw_message": "x", "category": "c", "max_total": "9", "assumptions": ["a"]}}</tool_call>'
WRONG_FIRST = '<tool_call>{"name": "search_catalog", "arguments": {"query": "x", "filters": {}}}</tool_call>'
BAD_ARGS = '<tool_call>{"name": "parse_intent", "arguments": {"raw_message": 5}}</tool_call>'  # envelope ok, schema bad
NO_CALL = "I would be glad to help you shop."
NOW = dt.datetime(2026, 11, 1, 12, tzinfo=dt.timezone.utc)


class Client:
    def __init__(self, outputs, cost="0.001"):
        self.outputs, self.n, self.cost = outputs, 0, cost

    def invoke(self, request, retry):
        self.rid = request.request_id
        raw = self.outputs[self.n % len(self.outputs)] if isinstance(self.outputs, list) else self.outputs(self.n, retry)
        self.n += 1
        return QwenInferenceResponse(raw_output=raw, prompt_tokens=100, completion_tokens=20, latency_ms=800 + self.n,
                                     finish_reason="stop", model="m", checkpoint="c", seed_supported=True, cost=self.cost)


def probe_with(outputs, **kw):
    return run_probe(QwenModelAdapter(Client(outputs), max_retries=1), clock=lambda: NOW, **kw)


def test_probe_counts_exactly_twenty_prompts_with_denominators_and_keeps_no_raw_output(tmp_path):
    report = probe_with([CALL])
    m = report["metrics"]
    assert report["status"] == "passed" and m["valid_structured_call"] == {"numerator": 20, "denominator": 20, "value": 1.0}
    assert m["schema_valid_arguments"] == {"numerator": 20, "denominator": 20, "value": 1.0}
    assert m["parse_intent_first"]["denominator"] == 20 and len(report["records"]) == 20
    assert m["latency_ms"]["measured_over"] == 20 and m["tokens"] == {"prompt": 2000, "completion": 400, "measured_over": 20}
    write(report, str(tmp_path / "p"))
    assert "<tool_call>" not in (tmp_path / "p.json").read_text() + (tmp_path / "p.md").read_text()


def test_pass_bar_is_recorded_separately_from_the_result_and_is_unchanged():
    report = probe_with([CALL])
    assert report["pass_bar"] == PASS_BAR and report["pass_bar"]["status"] == "proposed"
    assert THRESHOLDS == {"valid_structured_call": 0.90, "schema_valid_arguments": 0.90, "parse_intent_first": 0.90}
    assert report["result"] == {"status": "passed", "failed_thresholds": []} and "thresholds" not in report["result"]


def test_report_carries_identity_hashes_seed_authorization_and_timestamps():
    auth = {"token_rotated_confirmed": True, "billing_confirmed": True, "approved_ceiling_usd": "0.86"}
    report = probe_with([CALL], authorization=auth, checkpoint="qwen-lora-abcdef012345", adapter_hash="a" * 64,
                        training_manifest_hash="b" * 64)
    assert report["model"] == {"id": MODEL_ID, "revision": MODEL_REVISION, "checkpoint": "qwen-lora-abcdef012345",
                               "adapter_hash": "a" * 64, "training_manifest_hash": "b" * 64}
    assert report["prompt_manifest_sha256"] == prompt_manifest(probe.SEED)["sha256"] and len(report["tool_schema_sha256"]) == 64
    assert report["seed"] == probe.SEED and report["authorization"] == auth
    assert (report["started_at"], report["finished_at"]) == (NOW.isoformat(),) * 2


def test_tool_schema_hash_is_stable_and_tracks_the_offered_tools():
    assert probe.tool_schema_sha256() == probe.tool_schema_sha256() and len(probe.tool_schema_sha256()) == 64


def test_artifact_is_deterministic_for_identical_inputs(tmp_path):
    write(probe_with([CALL]), str(tmp_path / "a"))
    write(probe_with([CALL]), str(tmp_path / "b"))
    assert (tmp_path / "a.json").read_bytes() == (tmp_path / "b.json").read_bytes()


def test_malformed_and_wrong_first_tool_fail_the_bar_with_retries_counted():
    report = probe_with(lambda n, retry: NO_CALL if n % 4 == 0 else WRONG_FIRST if n % 4 == 1 else CALL)
    m = report["metrics"]
    assert report["status"] == "failed" and m["malformed"]["denominator"] == 20 and m["retries"] > 0
    assert m["parse_intent_first"]["numerator"] < m["valid_structured_call"]["numerator"]
    assert set(report["result"]["failed_thresholds"]) >= {"parse_intent_first"}


def test_schema_invalid_arguments_count_as_structured_calls_but_not_schema_valid():
    """Distinguishes 'did not emit a tool call' from 'emitted one with bad arguments' (the metrics are not vacuous)."""
    client = Client(lambda n, retry: BAD_ARGS if sum(map(ord, client.rid)) % 2 == 0 else CALL)  # same verdict on both attempts
    report = run_probe(QwenModelAdapter(client, max_retries=1), clock=lambda: NOW)
    m = report["metrics"]
    assert m["valid_structured_call"]["denominator"] == 20 and m["schema_valid_arguments"]["denominator"] == m["valid_structured_call"]["numerator"]
    assert m["schema_valid_arguments"]["numerator"] < m["schema_valid_arguments"]["denominator"]
    only_prose = probe_with([NO_CALL])["metrics"]
    assert only_prose["valid_structured_call"]["numerator"] == 0 and only_prose["schema_valid_arguments"]["value"] is None


def test_cost_is_unknown_without_a_meter_and_measured_total_when_supplied():
    assert probe_with([CALL])["metrics"]["cost_usd"]["total"] is None
    cost = probe_with([CALL], spent=lambda: Decimal("0.1234"), ceiling=Decimal("0.861948"))["metrics"]["cost_usd"]
    assert (cost["total"], cost["per_prompt"], cost["ceiling_exceeded"]) == ("0.1234", "0.00617", False)
    assert probe_with([CALL], spent=lambda: Decimal("1"), ceiling=Decimal("0.5"))["metrics"]["cost_usd"]["ceiling_exceeded"] is True


def test_unknown_per_call_cost_marks_the_total_as_not_known():
    class Unknown(Client):
        def invoke(self, request, retry):
            out = super().invoke(request, retry)
            return out.model_copy(update={"cost": None})

    report = run_probe(QwenModelAdapter(Unknown([CALL])), spent=lambda: Decimal("0.01"), clock=lambda: NOW)
    assert report["metrics"]["cost_usd"]["known"] is False


def test_without_authorization_nothing_runs_and_the_blocker_names_the_variables(tmp_path, monkeypatch, capsys):
    for k in ("CRUCIBLE_MODAL_TOKEN_ROTATED", "CRUCIBLE_MODAL_BILLING_CONFIRMED", "CRUCIBLE_MODAL_APPROVED_CEILING_USD"):
        monkeypatch.delenv(k, raising=False)
    assert main(["--out", str(tmp_path / "blocked")]) == 3
    saved = json.loads((tmp_path / "blocked.json").read_text())
    assert saved["status"] == "blocked_not_run" and saved["gpu_spend_usd"] == "0" and saved["metrics"] is None
    assert "CRUCIBLE_MODAL_BILLING_CONFIRMED" in saved["blocker"] and saved["pass_bar"] == PASS_BAR
    assert saved["authorization"] == {"token_rotated_confirmed": False, "billing_confirmed": False, "approved_ceiling_usd": None}
    assert saved["result"]["status"] == "blocked_not_run" and saved["prompt_manifest_sha256"]
    assert "passed" not in (tmp_path / "blocked.md").read_text().lower().replace("not run", "")


def test_blocked_report_never_claims_a_pass():
    assert blocked_report("x", clock=lambda: NOW)["status"] == "blocked_not_run"


def test_adapter_probe_uses_the_adapter_checkpoint_and_records_its_identity(tmp_path, monkeypatch):
    from tests.test_qwen_adapter_inference import FakeEngine, client_for, make_artifact
    from modal_app.qwen_service import AdapterResolver, QwenService
    manifest = make_artifact(tmp_path)
    engine = FakeEngine()
    service = QwenService(engine, AdapterResolver(tmp_path))
    seen = {}

    def factory(adapter=None):
        seen["adapter"] = adapter
        return client_for(service, adapter)

    path = tmp_path / "run-0001" / "final" / "artifact_manifest.json"
    code = main(["--adapter-manifest", str(path), "--out", str(tmp_path / "out" / "adapter_probe")], client_factory=factory)
    saved = json.loads((tmp_path / "out" / "adapter_probe.json").read_text())
    assert code == 0 and saved["status"] == "passed" and seen["adapter"] == manifest.selection
    assert saved["model"]["checkpoint"] == manifest.checkpoint_id and saved["model"]["adapter_hash"] == manifest.adapter_hash
    assert engine.calls == [manifest.checkpoint_id] * 20 and saved["metrics"]["cost_usd"]["total"] is not None
