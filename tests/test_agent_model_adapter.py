from decimal import Decimal

import pytest
from pydantic import ValidationError

from agents.actions import ParseIntent, SearchCatalog
from agents.model import (
    AdapterPolicy, ModelRequest, ScriptedModelAdapter, StructuredToolCall,
)
from tests.fixtures.scoring import feasible_task


def request(task, history=()):
    return ModelRequest(request_id="episode-1", task=task, history=history, seed=7, attempt=0,
                        system_prompt="research then decide", model_checkpoint="fixture-model")


def test_structured_tool_call_validates_into_typed_action():
    call = StructuredToolCall(name="parse_intent", arguments={
        "raw_message": "need shoes", "category": "running-shoes",
        "max_total": "100.00", "assumptions": ["size omitted"],
    })
    action = call.to_action()
    assert isinstance(action, ParseIntent) and action.max_total == Decimal("100.00")


def test_scripted_model_is_stateless_and_history_indexed():
    task = feasible_task()
    adapter = ScriptedModelAdapter({task.id: (
        ParseIntent(raw_message=task.raw_message, category="running-shoes",
                    max_total=Decimal("100"), assumptions=("size exact",)),
        SearchCatalog(query="shoes", filters={"category": "running-shoes"}),
    )})
    first = adapter.complete(request(task))
    assert first == adapter.complete(request(task))
    assert first.tool_call.name == "parse_intent"


def test_adapter_policy_rejects_malformed_structured_calls_fail_closed():
    task = feasible_task()
    adapter = ScriptedModelAdapter({task.id: (
        StructuredToolCall(name="propose_purchase", arguments={"product_id": "shoe-a"}),
    )})
    policy = AdapterPolicy(adapter, request_id="episode", seed=1,
                           system_prompt="grounded", model_checkpoint="fixture")
    with pytest.raises(ValidationError):
        policy.next_step(task, (), 0)
