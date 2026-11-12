"""Continuous/batched serving, shared cost, response cache and concurrent episodes: offline, no GPU, no Modal."""
import asyncio
from decimal import Decimal

from agents.model import QwenModelAdapter, ScriptedModelAdapter
from agents.qwen_client import ModalQwenClient
from memory import InMemoryTraceRepository
from modal_app.qwen_service import (AdapterResolver, AsyncQwenService, EngineOutput, GenerationCostMeter, InputTooLong,
                                    QwenService)
from modal_app.qwen_toolcalls import estimate_modal_cost
from tests.test_agent_qwen_client import GOOD, request, result
from tests.test_qwen_adapter_inference import base_request
from tests.test_world_model_generation import POLICY, run, world  # noqa: F401  (world is a fixture)
from world.store import GenerationStore, MemoryBlobStore


class BatchEngine:
    def __init__(self):
        self.batches = []

    def load_adapter(self, name, directory): ...
    def unload_adapter(self, name): ...

    def generate_batch(self, work):
        self.batches.append(len(work))
        return [InputTooLong() if r.max_new_tokens == 7 else
                EngineOutput(raw_output=f"out-{r.seed}", input_tokens=10, output_tokens=2, finish_reason="stop",
                             generation_seconds=4.0) for r, _ in work]


def test_batch_runs_valid_requests_in_one_engine_call_and_keeps_order(tmp_path):
    engine = BatchEngine()
    out = QwenService(engine, AdapterResolver(tmp_path)).handle_batch(
        [base_request(seed=1), {"bad": 1}, base_request(seed=2, max_new_tokens=7), base_request(seed=3)])
    assert engine.batches == [3]  # the invalid request never reaches the engine
    assert out[0]["raw_output"] == "out-1" and out[3]["raw_output"] == "out-3"
    assert out[1]["error_code"] == "invalid_request" and out[2]["error_code"] == "input_too_long"
    assert out[0]["batch_size"] == 3 and out[0]["generation_seconds"] == 4.0  # latency stays the true wall time


def test_batched_cost_is_shared_and_cache_replays_for_free(tmp_path):
    calls = []

    def transport(payload, timeout):
        calls.append(payload)
        return result(generation_seconds=4.0, batch_size=4)

    def make():
        return ModalQwenClient(transport, cost_ceiling=Decimal(1), timeout_seconds=1, cache_dir=tmp_path)

    first = make()
    out = QwenModelAdapter(first).generate(request())
    assert out.cost == Decimal(str(estimate_modal_cost(1.0)["total_usd"]))  # 4 s across 4 requests = 1 s each
    again = make()  # a new process: the cache is on disk
    replay = QwenModelAdapter(again).generate(request())
    assert len(calls) == 1 and again.cache_hits == 1 and replay.cost == 0 and replay.tool_calls == out.tool_calls
    QwenModelAdapter(again).generate(request(seed=8))  # a different request is never answered from the cache
    assert len(calls) == 2


def test_async_server_cost_uses_its_metered_share_not_full_request_latency():
    transport = lambda payload, timeout: result(generation_seconds=10.0, batch_size=1,
                                                billable_generation_seconds=2.0)
    client = ModalQwenClient(transport, cost_ceiling=Decimal(1), timeout_seconds=1)
    QwenModelAdapter(client).generate(request())
    assert client.spent == Decimal(str(estimate_modal_cost(2.0)["total_usd"]))


def test_async_continuous_batch_cost_shares_sum_to_gpu_busy_time():
    now = [0.0]
    meter = GenerationCostMeter(lambda: now[0])

    async def scenario():
        await meter.start("a")
        now[0] = 2.0
        await meter.start("b")           # a alone: 2 s
        now[0] = 6.0
        a = await meter.finish("a")      # a+b share 4 s: 2 s each
        now[0] = 8.0
        b = await meter.finish("b")      # b alone: 2 s
        return a, b

    a, b = asyncio.run(scenario())
    assert (a, b) == (4.0, 4.0) and a + b == 8.0


def test_async_request_cancellation_does_not_cancel_an_inflight_peer(tmp_path):
    entered = {1: asyncio.Event(), 2: asyncio.Event()}
    release = {1: asyncio.Event(), 2: asyncio.Event()}
    cancelled = []

    class AsyncEngine:
        async def generate(self, req, adapter):
            entered[req.seed].set()
            try:
                await release[req.seed].wait()
            except asyncio.CancelledError:
                cancelled.append(req.seed)
                raise
            return EngineOutput(raw_output=f"out-{req.seed}", input_tokens=3, output_tokens=1,
                                finish_reason="stop", generation_seconds=1.0,
                                billable_generation_seconds=0.5)

    async def scenario():
        service = AsyncQwenService(AsyncEngine(), AdapterResolver(tmp_path))
        first = asyncio.create_task(service.handle(base_request(seed=1)))
        second = asyncio.create_task(service.handle(base_request(seed=2)))
        await asyncio.gather(entered[1].wait(), entered[2].wait())
        first.cancel()
        try:
            await first
        except asyncio.CancelledError:
            pass
        release[2].set()
        return await second

    out = asyncio.run(scenario())
    assert cancelled == [1]
    assert out["raw_output"] == "out-2" and out["billable_generation_seconds"] == 0.5


def test_concurrent_episodes_record_the_same_outcomes_as_serial(world):  # noqa: F811
    outcomes = []
    for concurrency in (1, 4):
        res = run(world, GenerationStore(MemoryBlobStore()), InMemoryTraceRepository(), ScriptedModelAdapter(world[3]),
                  concurrency=concurrency)
        assert res.complete and res.state.compat.policy_id == POLICY
        outcomes.append((res.executed, res.state.outcomes))
    assert outcomes[0] == outcomes[1]  # same keys, same order, same fitness/kills


def test_concurrent_run_honours_max_episodes_and_resumes(world):  # noqa: F811
    store, traces = GenerationStore(MemoryBlobStore()), InMemoryTraceRepository()
    first = run(world, store, traces, ScriptedModelAdapter(world[3]), concurrency=4, max_episodes=5)
    assert not first.complete and len(first.executed) == 5
    rest = run(world, store, traces, ScriptedModelAdapter(world[3]), concurrency=4)
    assert rest.complete and len(rest.executed) == 27 and len({t.episode_id for t in traces.traces}) == 32


def test_vllm_batch_runs_one_generate_per_adapter_never_a_list_with_none(monkeypatch):
    import sys
    import types

    from modal_app.qwen_protocol import QwenRequest
    from modal_app.qwen_service import VLLMEngine

    monkeypatch.setitem(sys.modules, "vllm", types.SimpleNamespace(SamplingParams=lambda **kw: kw))

    class Tok:
        def apply_chat_template(self, messages, **kw): return messages[-1]["content"]
        def __call__(self, text): return {"input_ids": [1] * (9000 if text == "huge" else 3)}

    calls = []

    class LLM:
        def generate(self, prompts, params, *, use_tqdm, lora_request):
            calls.append((len(prompts), lora_request))
            out = types.SimpleNamespace(text="ok", token_ids=[1], finish_reason="stop")
            return [types.SimpleNamespace(outputs=[out], prompt_token_ids=p["prompt_token_ids"]) for p in prompts]

    engine = object.__new__(VLLMEngine)
    engine.tokenizer, engine.llm, engine.loras = Tok(), LLM(), {"a1": "LORA-A1"}

    def req(text):
        return QwenRequest(**base_request(seed=1) | {"messages": [{"role": "user", "content": text}]})

    out = engine.generate_batch([(req("x"), None), (req("y"), "a1"), (req("huge"), None), (req("z"), None)])
    assert sorted(calls, key=str) == sorted([(2, None), (1, "LORA-A1")], key=str)  # base group and adapter group
    assert isinstance(out[2], InputTooLong) and all(o.raw_output == "ok" for i, o in enumerate(out) if i != 2)
