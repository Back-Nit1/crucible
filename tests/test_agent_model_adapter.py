import datetime as dt
import json
from decimal import Decimal

import pytest

from agents.actions import (
    Compare,
    ConfirmAndPay,
    GetProduct,
    GetReviews,
    ParseIntent,
    ProposePurchase,
    ReportNoMatch,
    SearchCatalog,
    SummarizeReviewEvidence,
)
from agents.executor import InMemoryToolExecutor
from agents.model import (
    AdapterPolicy,
    MalformedModelOutput,
    Message,
    ModelRequest,
    QwenInferenceResponse,
    QwenModelAdapter,
    ScriptedModelAdapter,
    action_tools,
    parse_action,
    StructuredToolCall,
)
from agents.runner import run_episode
from payments.guards import GuardedPayments, idempotency_key
from payments.mock import MockPayments
from scoring.schemas import ReviewClaim, ReviewSort
from tasks.engine import build_task
from tasks.schemas import HardConstraints
from tests.fixtures.scoring import FIXTURE_MANIFEST, InMemoryCatalog, feasible_task


NOW = dt.datetime(2026, 10, 31, tzinfo=dt.UTC)


def request() -> ModelRequest:
    return ModelRequest(
        request_id="task-1",
        sequence=0,
        system_prompt="Use one typed shopping tool.",
        messages=(Message(role="user", content="need shoes"),),
        tools=action_tools(),
        seed=7,
    )


def block(name, arguments):
    return f"<tool_call>{json.dumps({'name': name, 'arguments': arguments})}</tool_call>"


class Client:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    def invoke(self, model_request, retry):
        self.calls.append((model_request, retry))
        raw = self.outputs.pop(0)
        return QwenInferenceResponse(
            raw_output=raw,
            prompt_tokens=10,
            completion_tokens=4,
            latency_ms=25,
            finish_reason="tool_calls",
            model="Qwen2.5-7B-Instruct",
            checkpoint="a09a3545",
            seed_supported=True,
            cost=Decimal("0.001"),
        )


def parse_arguments():
    return {
        "raw_message": "need shoes",
        "category": "running-shoes",
        "max_total": "100.00",
        "assumptions": ["size is not known"],
    }


def test_qwen_adapter_parses_native_calls_and_records_only_raw_hash():
    client = Client([block("parse_intent", parse_arguments())])
    output = QwenModelAdapter(client).generate(request())
    assert output.tool_calls[0].name == "parse_intent"
    assert output.prompt_tokens == 10 and output.completion_tokens == 4
    assert len(output.raw_output_hash) == 64
    assert "need shoes" not in json.dumps(output.metadata())


def test_tool_name_cannot_be_overridden_inside_arguments():
    tools = {tool.name: tool for tool in action_tools()}
    assert "type" not in tools["parse_intent"].parameters["properties"]
    with pytest.raises(ValueError, match="discriminator"):
        parse_action(StructuredToolCall(
            name="parse_intent",
            arguments={"type": "search_catalog", **parse_arguments()},
        ))


def test_qwen_adapter_retries_once_then_succeeds_deterministically():
    client = Client(["<tool_call>{broken}</tool_call>", block("parse_intent", parse_arguments())])
    adapter = QwenModelAdapter(client, max_retries=1)
    output = adapter.generate(request())
    assert output.retry_count == 1
    assert [retry for _, retry in client.calls] == [0, 1]
    assert len(adapter.audit) == 2 and "error" in adapter.audit[0]


@pytest.mark.parametrize(
    "raw",
    [
        "plain prose",
        block("invented_tool", {}),
        block("parse_intent", {"raw_message": "missing required fields"}),
        block("parse_intent", parse_arguments()) + block("search_catalog", {"query": "x"}),
    ],
)
def test_qwen_adapter_fails_closed_without_leaking_raw_output(raw):
    adapter = QwenModelAdapter(Client([raw]), max_retries=0)
    with pytest.raises(MalformedModelOutput) as caught:
        adapter.generate(request())
    assert raw not in str(caught.value)
    assert "raw_output_hash" in caught.value.attempts[0]


def executor(task, agent_id="agent-1"):
    catalog = InMemoryCatalog()
    backend = MockPayments(auto_approve=True)
    return backend, InMemoryToolExecutor(
        catalog,
        GuardedPayments(backend, catalog),
        task_id=task.id,
        agent_id=agent_id,
        budget_cap=task.hard_constraints.max_total,
        clock=lambda: NOW,
    )


def purchase_script(task, agent_id="agent-1"):
    return (
        ParseIntent(raw_message=task.raw_message, category="running-shoes", max_total=Decimal("100"), assumptions=("size 12",)),
        SearchCatalog(query="", filters={"category": "running-shoes"}),
        GetProduct(product_id="shoe-a"),
        GetReviews(product_id="shoe-a", focus="support", sort=ReviewSort.CRITICAL, limit=2),
        Compare(product_ids=("shoe-a", "shoe-b")),
        SummarizeReviewEvidence(
            product_id="shoe-a",
            user_context="runner seeking support",
            claims=(ReviewClaim(
                concern="cushioning",
                claim="The cited fixture review discusses supportive cushioning.",
                review_ids=("review-a-positive", "review-a-critical"),
            ),),
        ),
        ProposePurchase(product_id="shoe-a", variant="12", expected_total=Decimal("89"), assumptions=("size 12",)),
        ConfirmAndPay(
            pending_order_id=idempotency_key(task.id, agent_id, "shoe-a", "12"),
            user_confirmed=True,
        ),
    )


def play(task, actions, episode_id):
    backend, tool_executor = executor(task)
    adapter = ScriptedModelAdapter({task.id: actions})
    episode = run_episode(
        episode_id=episode_id,
        task=task,
        agent_id="agent-1",
        generation_id="gen-1",
        policy=AdapterPolicy(adapter, "Research safely.", seed=task.seed),
        executor=tool_executor,
        seed=task.seed,
        clock=lambda: NOW,
    )
    return episode, backend, adapter


def test_scripted_adapter_executes_review_grounded_purchase_through_model_boundary():
    task = feasible_task(seed=4)
    episode, backend, adapter = play(task, purchase_script(task), "ep-success")
    assert episode.termination == "success" and not episode.killed
    assert len(backend.ledger) == 1
    assert len(episode.model_metadata) == len(purchase_script(task))
    assert all(item["model"] == "scripted" for item in episode.model_metadata)
    assert len(adapter.requests) == len(purchase_script(task))


def test_scripted_adapter_supports_correct_no_match():
    catalog = InMemoryCatalog()
    task = build_task(
        task_id="no-match",
        catalog_snapshot_id="snap",
        catalog=catalog,
        manifest_hash=FIXTURE_MANIFEST,
        constraints=HardConstraints(category="running-shoes", max_total=Decimal("10")),
        seed=2,
    )
    actions = (
        ParseIntent(raw_message=task.raw_message, category="running-shoes", max_total=Decimal("10"), assumptions=("all-in cap",)),
        SearchCatalog(query="", filters={"category": "running-shoes"}),
        GetProduct(product_id="shoe-a"),
        Compare(product_ids=("shoe-a", "shoe-b")),
        ReportNoMatch(
            reason="every real option exceeds the cap",
            closest_product_id="shoe-a",
            why_it_misses="price is above $10",
            assumptions=("all-in cap",),
        ),
    )
    episode, backend, _ = play(task, actions, "ep-no-match")
    assert episode.termination == "no_match" and not episode.killed and backend.ledger == []


def test_scripted_adapter_can_deliberately_exercise_safety_and_research_failures():
    task = feasible_task(seed=5)
    prefix = purchase_script(task)[:5]
    unsafe = prefix + (
        ProposePurchase(product_id="shoe-a", variant="12", expected_total=Decimal("101"), assumptions=("size 12",)),
    )
    episode, backend, _ = play(task, unsafe, "ep-unsafe")
    assert episode.termination == "instant_kill" and backend.ledger == []

    poor = purchase_script(task)[:1] + (
        ProposePurchase(product_id="shoe-a", variant="12", expected_total=Decimal("89"), assumptions=("size 12",)),
    )
    episode, backend, _ = play(task, poor, "ep-poor")
    assert episode.termination == "malformed_action" and backend.ledger == []
