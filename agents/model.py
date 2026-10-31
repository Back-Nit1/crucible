"""Vendor-neutral structured tool-call model boundary."""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from agents.actions import Action, RecordedToolCall
from agents.runner import ActionPolicy, ModelStep
from tasks.schemas import TaskSpec


_ACTION_ADAPTER = TypeAdapter(Action)


class ModelContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class StructuredToolCall(ModelContract):
    name: str = Field(min_length=1)
    arguments: dict[str, object]

    def to_action(self) -> Action:
        return _ACTION_ADAPTER.validate_python({"type": self.name, **self.arguments})


class ModelRequest(ModelContract):
    request_id: str = Field(min_length=1)
    task: TaskSpec
    history: tuple[RecordedToolCall, ...]
    seed: int = Field(ge=0)
    attempt: int = Field(ge=0)
    system_prompt: str = Field(min_length=1)
    model_checkpoint: str = Field(min_length=1)


class ModelOutput(ModelContract):
    tool_call: StructuredToolCall
    token_count: int = Field(default=0, ge=0)
    cost: Decimal = Field(default=Decimal("0"), ge=0)
    adapter_version: str = Field(min_length=1)


class ModelAdapter(Protocol):
    """Production adapters return one structured tool call and never execute it."""

    version: str
    def complete(self, request: ModelRequest) -> ModelOutput | None: ...


class AdapterPolicy(ActionPolicy):
    """Bridge a ModelAdapter to the bounded episode runner."""

    def __init__(self, adapter: ModelAdapter, *, request_id: str, seed: int,
                 system_prompt: str, model_checkpoint: str):
        self.adapter = adapter
        self.request_id = request_id
        self.seed = seed
        self.system_prompt = system_prompt
        self.model_checkpoint = model_checkpoint

    def next_step(self, task: TaskSpec, history: tuple[RecordedToolCall, ...], attempt: int) -> ModelStep | None:
        output = self.adapter.complete(ModelRequest(
            request_id=self.request_id, task=task, history=history, seed=self.seed,
            attempt=attempt, system_prompt=self.system_prompt,
            model_checkpoint=self.model_checkpoint,
        ))
        if output is None:
            return None
        return ModelStep(action=output.tool_call.to_action(), token_count=output.token_count,
                         cost=output.cost)


class ScriptedModelAdapter:
    """Deterministic structured-call adapter for full-system and resume tests."""

    version = "scripted-model-v1"

    def __init__(self, scripts: dict[str, tuple[StructuredToolCall | Action, ...]],
                 *, token_count_per_call: int = 1, cost_per_call: Decimal = Decimal("0")):
        self.scripts = scripts
        self.token_count_per_call = token_count_per_call
        self.cost_per_call = cost_per_call

    def complete(self, request: ModelRequest) -> ModelOutput | None:
        script = self.scripts.get(request.task.id, ())
        index = len(request.history)
        if index >= len(script):
            return None
        item = script[index]
        if isinstance(item, StructuredToolCall):
            call = item
        else:
            payload = item.model_dump(mode="json")
            call = StructuredToolCall(name=payload.pop("type"), arguments=payload)
        return ModelOutput(tool_call=call, token_count=self.token_count_per_call,
                           cost=self.cost_per_call, adapter_version=self.version)
