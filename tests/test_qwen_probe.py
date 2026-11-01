import json

from agents.model import QwenInferenceResponse, QwenModelAdapter
from scripts.qwen_probe import blocked_report, main, run_probe, write

CALL = '<tool_call>{"name": "parse_intent", "arguments": {"raw_message": "x", "category": "c", "max_total": "9", "assumptions": ["a"]}}</tool_call>'


class Client:
    def __init__(self, outputs):
        self.outputs, self.n = outputs, 0

    def invoke(self, request, retry):
        raw = self.outputs[self.n % len(self.outputs)] if isinstance(self.outputs, list) else self.outputs(self.n, retry)
        self.n += 1
        return QwenInferenceResponse(raw_output=raw, prompt_tokens=100, completion_tokens=20, latency_ms=800 + self.n,
                                     finish_reason="stop", model="m", checkpoint="c", seed_supported=True, cost="0.001")


def test_probe_counts_exactly_twenty_prompts_with_denominators_and_keeps_no_raw_output(tmp_path):
    report = run_probe(QwenModelAdapter(Client([CALL]), max_retries=1))
    m = report["metrics"]
    assert report["status"] == "pass" and m["valid_structured_call"] == {"numerator": 20, "denominator": 20, "value": 1.0}
    assert m["latency_ms"]["measured_over"] == 20 and m["cost_usd"]["total"] == "0.020"
    write(report, str(tmp_path / "p"))
    assert "<tool_call>" not in (tmp_path / "p.json").read_text() + (tmp_path / "p.md").read_text()


def test_malformed_and_wrong_first_tool_fail_the_quality_bar_with_retries_counted():
    bad = "no tool here"
    wrong = '<tool_call>{"name": "search_catalog", "arguments": {"query": "x", "filters": {}}}</tool_call>'
    report = run_probe(QwenModelAdapter(Client(lambda n, retry: bad if n % 4 == 0 else wrong if n % 4 == 1 else CALL), max_retries=1))
    m = report["metrics"]
    assert report["status"] == "fail" and m["malformed"]["denominator"] == 20 and m["retries"] > 0
    assert m["parse_intent_first"]["numerator"] < m["valid_structured_call"]["numerator"]


def test_without_authorization_nothing_runs_and_the_blocker_names_the_variables(tmp_path, monkeypatch, capsys):
    for k in ("CRUCIBLE_MODAL_TOKEN_ROTATED", "CRUCIBLE_MODAL_BILLING_CONFIRMED", "CRUCIBLE_MODAL_APPROVED_CEILING_USD"):
        monkeypatch.delenv(k, raising=False)
    assert main(["--out", str(tmp_path / "blocked")]) == 3
    saved = json.loads((tmp_path / "blocked.json").read_text())
    assert saved["status"] == "blocked_not_run" and saved["gpu_spend_usd"] == "0" and saved["metrics"] is None
    assert "CRUCIBLE_MODAL_BILLING_CONFIRMED" in saved["blocker"]
