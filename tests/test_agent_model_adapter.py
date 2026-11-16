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
    available_action_tools,
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


def test_qwen_adapter_preserves_raw_output_and_hash():
    client = Client([block("parse_intent", parse_arguments())])
    output = QwenModelAdapter(client).generate(request())
    assert output.tool_calls[0].name == "parse_intent"
    assert output.prompt_tokens == 10 and output.completion_tokens == 4
    assert len(output.raw_output_hash) == 64
    assert output.metadata()["raw_output"] == block("parse_intent", parse_arguments())


def test_tool_name_cannot_be_overridden_inside_arguments():
    tools = {tool.name: tool for tool in action_tools()}
    assert "type" not in tools["parse_intent"].parameters["properties"]
    with pytest.raises(ValueError, match="discriminator"):
        parse_action(StructuredToolCall(
            name="parse_intent",
            arguments={"type": "search_catalog", **parse_arguments()},
        ))


def test_policy_offers_only_actions_whose_prerequisites_are_satisfied():
    task = feasible_task(seed=4)
    _, tool_executor = executor(task)

    assert [t.name for t in available_action_tools(())] == ["parse_intent"]
    tool_executor.execute(purchase_script(task)[0])
    assert [t.name for t in available_action_tools(tuple(tool_executor.records))] == ["search_catalog"]

    tool_executor.execute(purchase_script(task)[1])
    names = {t.name for t in available_action_tools(tuple(tool_executor.records))}
    assert names == {"search_catalog", "get_product", "report_no_match"}
    assert "get_reviews" not in names and "propose_purchase" not in names

    for action in purchase_script(task)[2:6]:
        tool_executor.execute(action)
    names = {t.name for t in available_action_tools(tuple(tool_executor.records))}
    assert "propose_purchase" in names and "confirm_and_pay" not in names
    offered = {tool.name: tool for tool in available_action_tools(tuple(tool_executor.records))}
    opened = {record.action.product_id for record in tool_executor.records
              if isinstance(record.action, GetProduct)}
    assert set(offered["get_reviews"].parameters["properties"]["product_id"]["enum"]) == opened

    tool_executor.execute(purchase_script(task)[6])
    assert [t.name for t in available_action_tools(tuple(tool_executor.records))] == ["confirm_and_pay"]


def test_qwen_adapter_retries_once_then_succeeds_deterministically():
    client = Client(["<tool_call>{broken}</tool_call>", block("parse_intent", parse_arguments())])
    adapter = QwenModelAdapter(client, max_retries=1)
    output = adapter.generate(request())
    assert output.retry_count == 1
    assert [retry for _, retry in client.calls] == [0, 1]
    assert len(adapter.audit) == 2 and "error" in adapter.audit[0]
    first, second = (req for req, _ in client.calls)
    assert second.messages[:-2] == first.messages == request().messages  # history itself is never altered
    assert second.temperature == Decimal("0.3") and first.temperature == 0  # the retry samples; the first try is greedy
    assert second.tools == first.tools and second.system_prompt == first.system_prompt  # full schemas on every attempt
    assert second.messages[-2].content == "<tool_call>{broken}</tool_call>" and "rejected" in second.messages[-1].content
    assert "Tools available now: " in second.messages[-1].content and "parse_intent" in second.messages[-1].content


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


def test_empty_search_does_not_offer_refusal_with_fake_closest_product():
    from types import SimpleNamespace
    history = (SimpleNamespace(action=SearchCatalog(query='unmatched'), result_references=()),)
    assert [tool.name for tool in available_action_tools(history)] == ['search_catalog']


def test_review_summary_schema_requires_a_concern_and_lists_only_the_review_ids_that_were_read():
    task = feasible_task(seed=4)
    _, tool_executor = executor(task)
    for action in purchase_script(task)[:4]:
        tool_executor.execute(action)
    tool = {t.name: t for t in available_action_tools(tuple(tool_executor.records))}["summarize_review_evidence"]
    claim = tool.parameters["$defs"]["ReviewClaim"]
    read = sorted(tool_executor.records[3].result_references)
    assert claim["required"] == ["concern", "claim", "review_ids"] and claim["properties"]["concern"]["type"] == "string"
    assert claim["properties"]["review_ids"]["items"]["enum"] == read


def test_a_repeated_review_id_inside_one_claim_is_collapsed_not_rejected():
    ids = ["review-a-positive", "review-a-positive", "review-a-critical"]
    action = parse_action(StructuredToolCall(name="summarize_review_evidence", arguments={
        "product_id": "shoe-a", "user_context": "x", "claims": [{"concern": "fit", "claim": "snug", "review_ids": ids}]}))
    assert action.claims[0].review_ids == ("review-a-positive", "review-a-critical")


def test_a_complete_tool_call_without_the_closing_tag_is_accepted_but_a_cut_off_one_is_not():
    body = '<tool_call>\n{"name": "parse_intent", "arguments": ' + json.dumps(parse_arguments()) + "}"
    adapter = QwenModelAdapter(Client([body]), max_retries=0)
    assert adapter.generate(request()).tool_calls[0].name == "parse_intent"
    with pytest.raises(MalformedModelOutput):
        QwenModelAdapter(Client([body[:-40]]), max_retries=0).generate(request())
