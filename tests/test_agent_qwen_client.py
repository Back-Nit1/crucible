"""ModalQwenClient with an injected transport: no network, no GPU, no Modal import."""
import json
import threading
from decimal import Decimal

import pytest

from agents.model import (InferenceError, MalformedModelOutput, Message, ModelRequest, QwenInferenceResponse,
                          QwenModelAdapter, ToolDefinition, action_tools)
from agents.qwen_client import ModalQwenClient, require_launch_authorization
from modal_app.qwen_toolcalls import MODEL_ID, MODEL_REVISION

GOOD = '<tool_call>{"name": "parse_intent", "arguments": {"raw_message": "need shoes", "category": "shoes", ' \
       '"max_total": "50", "assumptions": ["all-in cap"]}}</tool_call>'


def request(**kw) -> ModelRequest:
    base = dict(request_id="g:a:t", sequence=0, system_prompt="one tool per turn", seed=7, temperature=0,
                checkpoint="qwen-base", messages=(Message(role="user", content="need shoes"),), tools=action_tools())
    return ModelRequest(**{**base, **kw})


def result(raw=GOOD, **kw):
    return {"raw_output": raw, "input_tokens": 120, "output_tokens": 30, "finish_reason": "stop", "model": MODEL_ID,
            "revision": MODEL_REVISION, "seed_applied": True, "generation_seconds": 1.5, "container_load_seconds": 0.0,
            **kw}


class Fake:
    def __init__(self, *responses):
        self.responses, self.payloads, self.cancelled = list(responses), [], 0

    def __call__(self, payload, timeout):
        self.payloads.append(payload)
        r = self.responses.pop(0)
        if isinstance(r, BaseException):
            raise r
        return r

    def cancel(self):
        self.cancelled += 1


def client(transport, **kw):
    return ModalQwenClient(transport, cost_ceiling=Decimal("0.861948"), timeout_seconds=1, **kw)


def test_valid_call_returns_every_required_field_and_sends_pinned_payload():
    t = Fake(result())
    out = QwenModelAdapter(client(t)).generate(request())
    assert out.tool_calls[0].name == "parse_intent"
    assert (out.prompt_tokens, out.completion_tokens, out.latency_ms, out.finish_reason) == (120, 30, 1500, "stop")
    assert (out.model, out.checkpoint, out.seed_supported, out.cost_known) == (MODEL_ID, MODEL_REVISION, True, True)
    assert out.cost > 0 and len(out.raw_output_hash) == 64
    p = t.payloads[0]
    assert (p["system"], p["seed"], p["model"], p["revision"]) == ("one tool per turn", 7, MODEL_ID, MODEL_REVISION)
    assert {x["function"]["name"] for x in p["tools"]} == {x.name for x in action_tools()}
    assert p["messages"] == [{"role": "user", "content": "need shoes"}]


def test_malformed_output_is_retried_boundedly_then_fails_closed_without_keeping_raw_text():
    raw = "I would love to help! <tool_call>{not json</tool_call> SECRET-RAW"
    t = Fake(result(raw), result(raw))
    adapter = QwenModelAdapter(client(t), max_retries=1)
    with pytest.raises(MalformedModelOutput):
        adapter.generate(request())
    assert len(t.payloads) == 2 and [p["seed"] for p in t.payloads] == [7, 8]       # retried once, new seed
    assert "SECRET-RAW" not in json.dumps(adapter.audit) and all(len(a["raw_output_hash"]) == 64 for a in adapter.audit)


def test_unoffered_unknown_or_overriding_tools_are_rejected():
    only_search = request(tools=tuple(t for t in action_tools() if t.name == "search_catalog"))
    for raw in (GOOD,  # real tool, but not offered in this request
                '<tool_call>{"name": "rm_rf", "arguments": {}}</tool_call>',
                '<tool_call>{"name": "search_catalog", "arguments": {"query": "x", "filters": {}, "type": "confirm_and_pay"}}</tool_call>'):
        with pytest.raises(MalformedModelOutput):
            QwenModelAdapter(client(Fake(result(raw))), max_retries=0).generate(only_search)


def test_timeout_cancels_and_is_a_structured_retryable_error_then_bounded():
    gate = threading.Event()

    class Slow(Fake):
        def __call__(self, payload, timeout):
            self.payloads.append(payload)
            gate.wait(10)

    t = Slow()
    c = ModalQwenClient(t, cost_ceiling=Decimal(1), timeout_seconds=0.05, grace_seconds=0)
    try:
        with pytest.raises(InferenceError) as e:
            QwenModelAdapter(c, max_retries=1).generate(request())
    finally:
        gate.set()
    assert e.value.code == "timeout" and e.value.retryable and t.cancelled == 2 and len(t.payloads) == 2


def test_transport_errors_never_leak_their_message():
    t = Fake(RuntimeError("401 https://x.modal.run?token=ak-SECRET123456"), ConnectionError("ak-SECRET123456"))
    with pytest.raises(InferenceError) as e:
        QwenModelAdapter(client(t), max_retries=1).generate(request())
    assert e.value.code == "transport_error" and "SECRET" not in str(e.value) and e.value.__cause__ is None


def test_wrong_model_identity_and_bad_schema_fail_closed():
    t = Fake(result(revision="deadbeef" * 5), result())
    with pytest.raises(InferenceError) as e:                      # non-retryable: raised immediately, one call only
        QwenModelAdapter(client(t), max_retries=2).generate(request())
    assert e.value.code == "model_identity_mismatch" and len(t.payloads) == 1
    with pytest.raises(InferenceError) as e:
        QwenModelAdapter(client(Fake({"raw_output": "x"})), max_retries=0).generate(request())
    assert e.value.code == "invalid_response"
    t = Fake({"error_code": 7}, result())                         # malformed refusal: still a refusal, not retried
    with pytest.raises(InferenceError) as e:
        QwenModelAdapter(client(t), max_retries=2).generate(request())
    assert e.value.code == "invalid_refusal" and not e.value.retryable and len(t.payloads) == 1
    with pytest.raises(InferenceError) as e:                      # a request pinning another checkpoint is refused
        client(Fake(result())).invoke(request(checkpoint="some-other-adapter"), 0)
    assert e.value.code == "checkpoint_mismatch"


def test_cost_ceiling_stops_further_calls_and_unknown_cost_is_not_free():
    c = ModalQwenClient(Fake(result(generation_seconds=1000), result()), cost_ceiling=Decimal("0.2"), timeout_seconds=1)
    assert c.invoke(request(), 0).cost > Decimal("0.2") and c.spent > 0
    with pytest.raises(InferenceError) as e:
        c.invoke(request(), 0)
    assert e.value.code == "cost_ceiling_reached"
    # an unknown cost stays unknown through the adapter
    class Unknown:
        def invoke(self, req, retry):
            return QwenInferenceResponse(raw_output=GOOD, prompt_tokens=1, completion_tokens=1, latency_ms=1,
                                         finish_reason="stop", model="m", checkpoint="c", cost=None)
    out = QwenModelAdapter(Unknown()).generate(request())
    assert out.cost_known is False and out.cost == 0


def test_gpu_cannot_be_reached_without_explicit_authorization():
    with pytest.raises(InferenceError) as e:
        require_launch_authorization({})
    for name in ("CRUCIBLE_MODAL_TOKEN_ROTATED", "CRUCIBLE_MODAL_BILLING_CONFIRMED", "CRUCIBLE_MODAL_APPROVED_CEILING_USD"):
        assert name in str(e.value)
    with pytest.raises(InferenceError):
        ModalQwenClient.from_environment({"CRUCIBLE_MODAL_TOKEN_ROTATED": "1"})
    with pytest.raises(InferenceError):                              # a ceiling of 0 / garbage is not an approval
        require_launch_authorization({"CRUCIBLE_MODAL_TOKEN_ROTATED": "1", "CRUCIBLE_MODAL_BILLING_CONFIRMED": "1",
                                      "CRUCIBLE_MODAL_APPROVED_CEILING_USD": "abc"})
    ok = {"CRUCIBLE_MODAL_TOKEN_ROTATED": "1", "CRUCIBLE_MODAL_BILLING_CONFIRMED": "1",
          "CRUCIBLE_MODAL_APPROVED_CEILING_USD": "0.861948"}
    assert require_launch_authorization(ok) == Decimal("0.861948")


def test_tool_history_is_rendered_in_qwen_message_format():
    msgs = (Message(role="user", content="need shoes"),
            Message(role="assistant", tool_name="get_product", tool_arguments={"product_id": "P1"}),
            Message(role="tool", tool_name="get_product", tool_result={"references": ["P1"], "summary": "ok", "error_code": None}))
    t = Fake(result())
    QwenModelAdapter(client(t)).generate(request(messages=msgs, sequence=1))
    sent = t.payloads[0]["messages"]
    assert sent[1]["tool_calls"][0]["function"] == {"name": "get_product", "arguments": {"product_id": "P1"}}
    assert sent[2]["role"] == "tool" and json.loads(sent[2]["content"])["references"] == ["P1"]


def test_server_contract_is_strict_and_the_server_module_never_attaches_a_gpu_by_default(monkeypatch):
    from pydantic import ValidationError
    from modal_app.qwen_protocol import QwenRequest
    base = dict(system="s", messages=[], tools=[{"type": "function"}], seed=1, temperature=0, max_new_tokens=16)
    QwenRequest(**base)
    for bad in ({"extra": 1}, {"max_new_tokens": 10_000}, {"seed": -1}, {"temperature": 5}):
        with pytest.raises(ValidationError):
            QwenRequest(**{**base, **bad})
    monkeypatch.delenv("CRUCIBLE_ENABLE_L4_PROBE", raising=False)
    import importlib
    import modal_app.qwen_inference as server
    assert importlib.reload(server).ENABLED is False
