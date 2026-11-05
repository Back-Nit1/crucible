"""Adapter-aware inference, end to end offline: ModalQwenClient -> (injected transport) -> QwenService -> fake engine.
The fake engine records which adapter each call used, so 'no silent base fallback' is asserted on the engine itself."""
import datetime as dt
from decimal import Decimal
from pathlib import Path

import pytest

from agents.model import InferenceError, Message, ModelRequest, QwenModelAdapter, action_tools
from agents.qwen_client import ModalQwenClient
from modal_app.adapter_artifact import (ADAPTER_CONFIG, ADAPTER_WEIGHTS, LineageEntry, Segment, hash_adapter_dir,
                                        seal_manifest, write_manifest, MANIFEST_FILENAME)
from modal_app.qwen_protocol import MAX_INPUT_CHARS, QwenRequest
from modal_app.qwen_service import AdapterResolver, EngineOutput, InputTooLong, MAX_LOADED_ADAPTERS, QwenService
from modal_app.qwen_toolcalls import MODEL_ID, MODEL_REVISION

GOOD = '<tool_call>{"name": "parse_intent", "arguments": {"raw_message": "need shoes", "category": "shoes", ' \
       '"max_total": "50", "assumptions": ["all-in cap"]}}</tool_call>'
T = dt.datetime(2026, 11, 1, tzinfo=dt.timezone.utc)


class FakeEngine:
    def __init__(self):
        self.calls, self.loaded, self.fail_load = [], {}, False

    def load_adapter(self, name, directory):
        if self.fail_load:
            raise RuntimeError("cuda oom with /secret/path")
        self.loaded[name] = directory

    def unload_adapter(self, name):
        self.loaded.pop(name)

    def generate(self, request, adapter):
        self.calls.append(adapter)
        if request.max_new_tokens == 7:
            raise InputTooLong
        return EngineOutput(raw_output=GOOD, input_tokens=100, output_tokens=20, finish_reason="stop", generation_seconds=1.0)


def make_artifact(root: Path, run_id="run-0001", weights=b"w1", **over):
    final = root / run_id / "final"
    final.mkdir(parents=True)
    (final / ADAPTER_CONFIG).write_text("{}")
    (final / ADAPTER_WEIGHTS).write_bytes(weights)
    fields = dict(run_id=run_id, base_model=MODEL_ID, base_revision=MODEL_REVISION, adapter_files=hash_adapter_dir(final),
                  training_manifest_hash="b" * 64, dataset_hash="c" * 64, data_source_model_version="scripted-v1",
                  dataset_record_count=3, plan_hash="d" * 64, hyperparameters={}, total_steps=2, steps_completed=2,
                  epochs_completed=1, checkpoint_lineage=(LineageEntry(step=2, epoch=0, state_sha256="a" * 64),),
                  segments=(Segment(start_step=0, end_step=2, duration_seconds=3.0),), gpu="L4", created_at=T)
    manifest = seal_manifest(**{**fields, **over})
    write_manifest(manifest, final / MANIFEST_FILENAME)
    return manifest


@pytest.fixture
def rig(tmp_path):
    engine = FakeEngine()
    service = QwenService(engine, AdapterResolver(tmp_path), container_load_seconds=2.5)
    return engine, service, tmp_path


def base_request(**kw):
    return {"system": "s", "messages": [{"role": "user", "content": "hi"}], "tools": [{"type": "function"}], "seed": 1,
            "temperature": 0, "max_new_tokens": 8, **kw}


def client_for(service, adapter=None, **kw):
    return ModalQwenClient(lambda payload, timeout: service.handle(payload), cost_ceiling=Decimal("1"), timeout_seconds=1,
                           adapter=adapter, **kw)


def mreq(**kw):
    return ModelRequest(**{**dict(request_id="g:a:t", sequence=0, system_prompt="p", seed=3, temperature=0,
                                  messages=(Message(role="user", content="need shoes"),), tools=action_tools()), **kw})


# ---- wire contract -------------------------------------------------------------------------------------------------
def test_base_request_is_valid_and_serializes_without_an_adapter_key():
    payload = QwenRequest(system="s", messages=[], tools=[{"x": 1}], seed=1, temperature=0, max_new_tokens=8)
    assert payload.adapter is None and "adapter" not in payload.model_dump(mode="json", exclude_none=True)


def test_oversized_input_and_path_like_adapter_identity_are_rejected_by_the_schema():
    with pytest.raises(ValueError):
        QwenRequest(system="x" * (MAX_INPUT_CHARS + 1), messages=[], tools=[{"x": 1}], seed=1, temperature=0, max_new_tokens=8)
    with pytest.raises(ValueError):
        QwenRequest(**base_request(adapter={"run_id": "../../etc", "adapter_hash": "a" * 64, "training_manifest_hash": "b" * 64}))


# ---- service -------------------------------------------------------------------------------------------------------
def test_base_request_uses_no_adapter_and_response_has_no_adapter_identity(rig):
    engine, service, _ = rig
    out = service.handle(base_request())
    assert engine.calls == [None] and "adapter_hash" not in out and out["container_load_seconds"] == 2.5
    assert service.handle(base_request())["container_load_seconds"] == 0  # reported once per container


def test_adapter_request_runs_the_verified_adapter_and_reports_its_identity(rig):
    engine, service, root = rig
    m = make_artifact(root)
    out = service.handle(base_request(adapter=m.selection.model_dump()))
    assert engine.calls == [m.checkpoint_id] and engine.loaded[m.checkpoint_id] == root / "run-0001" / "final"
    assert (out["adapter_run_id"], out["adapter_hash"], out["training_manifest_hash"]) == ("run-0001", m.adapter_hash, "b" * 64)
    again = service.handle(base_request(adapter=m.selection.model_dump()))
    assert again["adapter_load_seconds"] == 0 and len(engine.loaded) == 1


@pytest.mark.parametrize("mutate, code", [
    (lambda s: {**s, "adapter_hash": "0" * 64}, "adapter_hash_mismatch"),
    (lambda s: {**s, "training_manifest_hash": "0" * 64}, "training_manifest_mismatch"),
    (lambda s: {**s, "run_id": "run-9999"}, "adapter_missing"),
])
def test_mismatched_selection_is_rejected_before_inference_and_never_falls_back_to_base(rig, mutate, code):
    engine, service, root = rig
    m = make_artifact(root)
    out = service.handle(base_request(adapter=mutate(m.selection.model_dump())))
    assert out["error_code"] == code and engine.calls == [] and engine.loaded == {}


def test_adapter_trained_on_another_base_revision_is_rejected(rig):
    engine, service, root = rig
    m = make_artifact(root, base_revision="f" * 40)
    out = service.handle(base_request(adapter=m.selection.model_dump()))
    assert out["error_code"] == "base_model_mismatch" and engine.calls == []


def test_tampered_adapter_bytes_and_manifest_are_rejected(rig):
    engine, service, root = rig
    m = make_artifact(root)
    (root / "run-0001" / "final" / ADAPTER_WEIGHTS).write_bytes(b"evil")
    assert service.handle(base_request(adapter=m.selection.model_dump()))["error_code"] == "adapter_content_mismatch"
    (root / "run-0001" / "final" / MANIFEST_FILENAME).write_text('{"run_id": "run-0001"}')
    assert service.handle(base_request(adapter=m.selection.model_dump()))["error_code"] == "invalid_manifest"
    assert engine.calls == []


def test_adapter_load_failure_is_a_rejection_not_a_base_answer_and_leaks_no_message(rig):
    engine, service, root = rig
    m = make_artifact(root)
    engine.fail_load = True
    out = service.handle(base_request(adapter=m.selection.model_dump()))
    assert out == {"error_code": "adapter_load_failed", "detail": "RuntimeError"} and engine.calls == []


def test_wrong_model_revision_invalid_request_and_input_too_long_are_structured_refusals(rig):
    engine, service, _ = rig
    assert service.handle(base_request(revision="f" * 40))["error_code"] == "model_revision_mismatch"
    assert service.handle({"system": ""})["error_code"] == "invalid_request"
    assert service.handle(base_request(max_new_tokens=7))["error_code"] == "input_too_long"


def test_loaded_adapters_are_capped_and_oldest_is_unloaded(rig):
    engine, service, root = rig
    selections = [make_artifact(root, run_id=f"run-{i:04d}", weights=f"w{i}".encode()).selection for i in range(MAX_LOADED_ADAPTERS + 1)]
    for s in selections:
        assert "error_code" not in service.handle(base_request(adapter=s.model_dump()))
    assert len(engine.loaded) == MAX_LOADED_ADAPTERS and selections[0].checkpoint_id not in engine.loaded


# ---- client --------------------------------------------------------------------------------------------------------
def test_adapter_client_returns_adapter_checkpoint_identity_and_adapter_cost(rig):
    engine, service, root = rig
    m = make_artifact(root)
    out = QwenModelAdapter(client_for(service, m.selection)).generate(mreq(checkpoint=m.checkpoint_id))
    assert out.checkpoint == m.checkpoint_id and out.model == MODEL_ID and out.cost_known and out.cost > 0
    assert engine.calls == [m.checkpoint_id]


def test_base_client_still_serves_base_with_qwen_base_or_revision(rig):
    engine, service, _ = rig
    for label in ("qwen-base", MODEL_REVISION, None):
        out = QwenModelAdapter(client_for(service)).generate(mreq(checkpoint=label))
        assert out.checkpoint == MODEL_REVISION
    assert engine.calls == [None, None, None]


def test_base_request_on_an_adapter_client_is_refused_not_answered_from_base(rig):
    engine, service, root = rig
    m = make_artifact(root)
    for label in ("qwen-base", MODEL_REVISION):
        with pytest.raises(InferenceError) as err:
            client_for(service, m.selection).invoke(mreq(checkpoint=label), 0)
        assert err.value.code == "checkpoint_mismatch"
    with pytest.raises(InferenceError) as err:
        client_for(service).invoke(mreq(checkpoint=m.checkpoint_id), 0)  # adapter request on a base client
    assert err.value.code == "checkpoint_mismatch" and engine.calls == []


def test_client_surfaces_server_refusal_codes(rig):
    _, service, root = rig
    m = make_artifact(root)
    bad = m.selection.model_copy(update={"adapter_hash": "0" * 64})
    with pytest.raises(InferenceError) as err:
        client_for(service, bad).invoke(mreq(checkpoint=bad.checkpoint_id), 0)
    assert err.value.code == "adapter_hash_mismatch" and not err.value.retryable


def test_client_rejects_a_server_that_answers_from_the_wrong_model(rig):
    """A buggy or stale server that ignores `adapter` and answers from the base model must be caught by the client."""
    engine, service, root = rig
    m = make_artifact(root)

    def ignoring_server(payload, timeout):
        return service.handle({k: v for k, v in payload.items() if k != "adapter"})

    c = ModalQwenClient(ignoring_server, cost_ceiling=Decimal("1"), timeout_seconds=1, adapter=m.selection)
    with pytest.raises(InferenceError) as err:
        c.invoke(mreq(checkpoint=m.checkpoint_id), 0)
    assert err.value.code == "model_identity_mismatch"

    def adding_server(payload, timeout):
        return service.handle({**payload, "adapter": m.selection.model_dump()})

    base = ModalQwenClient(adding_server, cost_ceiling=Decimal("1"), timeout_seconds=1)
    with pytest.raises(InferenceError) as err:
        base.invoke(mreq(checkpoint="qwen-base"), 0)
    assert err.value.code == "model_identity_mismatch"


def test_adapter_client_label_must_be_its_checkpoint_id(rig):
    _, service, root = rig
    m = make_artifact(root)
    with pytest.raises(ValueError):
        client_for(service, m.selection, checkpoint_label="qwen-base")
