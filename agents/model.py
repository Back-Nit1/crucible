"""Production model boundary for typed shopping actions."""

from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from agents.actions import (
    Action,
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
from agents.runner import ActionPolicy, ModelStep
from tasks.schemas import TaskSpec


class ModelContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Message(ModelContract):
    role: Literal["user", "assistant", "tool"]
    content: str = ""
    tool_name: str | None = None
    tool_arguments: dict[str, object] | None = None
    tool_result: dict[str, object] | None = None


class ToolDefinition(ModelContract):
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    parameters: dict[str, object]


class StructuredToolCall(ModelContract):
    name: str = Field(min_length=1)
    arguments: dict[str, object]


class ModelRequest(ModelContract):
    request_id: str = Field(min_length=1)
    sequence: int = Field(ge=0)
    system_prompt: str = Field(min_length=1)
    messages: tuple[Message, ...]
    tools: tuple[ToolDefinition, ...]
    seed: int | None = Field(default=None, ge=0)
    temperature: Decimal = Field(default=Decimal("0"), ge=0, le=2)
    checkpoint: str | None = None  # pinned model/checkpoint the caller expects; a client must refuse a different one


class ModelOutput(ModelContract):
    tool_calls: tuple[StructuredToolCall, ...]
    malformed: bool = False
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    latency_ms: int = Field(default=0, ge=0)
    finish_reason: str = Field(default="tool_call", min_length=1)
    model: str = Field(min_length=1)
    checkpoint: str = Field(min_length=1)
    seed_supported: bool = False
    cost: Decimal = Field(default=Decimal("0"), ge=0)
    cost_known: bool = True  # False: `cost` is a placeholder 0 and the real spend is unknown
    raw_output_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    retry_count: int = Field(default=0, ge=0)

    def metadata(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude={"tool_calls"})


class ModelAdapter(Protocol):
    def generate(self, request: ModelRequest) -> ModelOutput: ...


_ACTION_TYPES = (
    ParseIntent,
    SearchCatalog,
    GetProduct,
    Compare,
    GetReviews,
    SummarizeReviewEvidence,
    ProposePurchase,
    ConfirmAndPay,
    ReportNoMatch,
)
_ACTION_BY_NAME = {model.model_fields["type"].default: model for model in _ACTION_TYPES}


def action_tools() -> tuple[ToolDefinition, ...]:
    tools = []
    for name, model in _ACTION_BY_NAME.items():
        parameters = model.model_json_schema()
        parameters.get("properties", {}).pop("type", None)
        parameters["required"] = [field for field in parameters.get("required", []) if field != "type"]
        tools.append(
            ToolDefinition(
                name=name,
                description=(model.__doc__ or f"Execute {name}.").strip(),
                parameters=parameters,
            )
        )
    return tuple(tools)


def parse_action(call: StructuredToolCall) -> Action:
    if call.name not in _ACTION_BY_NAME:
        raise ValueError(f"unknown tool {call.name!r}")
    if "type" in call.arguments:
        raise ValueError("tool arguments cannot override the action discriminator")
    return _ACTION_BY_NAME[call.name].model_validate({"type": call.name, **call.arguments})


class ScriptedModelAdapter:
    """Stateless deterministic model double keyed by request and history length."""

    def __init__(self, scripts: dict[str, tuple[Action, ...]], *, checkpoint: str = "script-v1"):
        self.scripts = scripts
        self.checkpoint = checkpoint
        self.requests: list[ModelRequest] = []

    def generate(self, request: ModelRequest) -> ModelOutput:
        self.requests.append(request)
        script = self.scripts.get(request.request_id)
        if script is None or request.sequence >= len(script):
            raise RuntimeError(f"no scripted action for {request.request_id}:{request.sequence}")
        action = script[request.sequence]
        payload = action.model_dump(mode="json", exclude={"type"})
        canonical = json.dumps({"name": action.type, "arguments": payload}, sort_keys=True, separators=(",", ":"))
        return ModelOutput(
            tool_calls=(StructuredToolCall(name=action.type, arguments=payload),),
            model="scripted",
            checkpoint=self.checkpoint,
            seed_supported=True,
            raw_output_hash=hashlib.sha256(canonical.encode()).hexdigest(),
        )


class QwenInferenceResponse(ModelContract):
    raw_output: str
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    latency_ms: int = Field(ge=0)
    finish_reason: str = Field(min_length=1)
    model: str = Field(min_length=1)
    checkpoint: str = Field(min_length=1)
    seed_supported: bool = False
    cost: Decimal | None = Field(default=Decimal("0"), ge=0)  # None = unknown (never silently reported as free)


TRANSIENT_CODES = frozenset({"timeout", "transport_error", "invalid_response"})  # the only retryable failures


class InferenceError(RuntimeError):
    """Structured, secret-free inference failure. Retryable iff the code is transient: content, identity, checkpoint
    and authorization refusals are never retried, whoever raises them."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code, self.retryable = code, code in TRANSIENT_CODES


class QwenInferenceClient(Protocol):
    """Implemented by Agent 1's Modal inference client, not the episode runner."""

    def invoke(self, request: ModelRequest, retry: int) -> QwenInferenceResponse: ...


class MalformedModelOutput(ValueError):
    def __init__(self, attempts: tuple[dict[str, object], ...]):
        super().__init__("model output failed closed after bounded retries")
        self.attempts = attempts


_TOOL_BLOCK = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL)


def _native_calls(raw_output: str) -> tuple[StructuredToolCall, ...]:
    blocks = _TOOL_BLOCK.findall(raw_output)
    if raw_output.count("<tool_call>") != len(blocks) or len(blocks) != 1:
        raise ValueError("response must contain exactly one closed tool call")
    payload = json.loads(blocks[0])
    if not isinstance(payload, dict) or not isinstance(payload.get("name"), str):
        raise ValueError("invalid tool-call envelope")
    arguments = payload.get("arguments")
    if isinstance(arguments, str):
        arguments = json.loads(arguments)
    if not isinstance(arguments, dict):
        raise ValueError("tool arguments must be an object")
    return (StructuredToolCall(name=payload["name"], arguments=arguments),)


class QwenModelAdapter:
    def __init__(self, client: QwenInferenceClient, *, max_retries: int = 1):
        if max_retries < 0 or max_retries > 3:
            raise ValueError("max_retries must be between zero and three")
        self.client = client
        self.max_retries = max_retries
        self.audit: list[dict[str, object]] = []

    def generate(self, request: ModelRequest) -> ModelOutput:
        attempts: list[dict[str, object]] = []
        offered = {tool.name for tool in request.tools}
        for retry in range(self.max_retries + 1):
            try:
                response = self.client.invoke(request, retry)
            except InferenceError as exc:
                audit = {"request_id": request.request_id, "sequence": request.sequence, "retry": retry, "error": exc.code}
                attempts.append(audit)
                self.audit.append(audit)
                if not exc.retryable or retry == self.max_retries:
                    raise
                continue
            raw_hash = hashlib.sha256(response.raw_output.encode()).hexdigest()
            audit = {
                "request_id": request.request_id,
                "sequence": request.sequence,
                "retry": retry,
                "raw_output_hash": raw_hash,
                "latency_ms": response.latency_ms,
                "model": response.model,
                "checkpoint": response.checkpoint,
            }
            try:
                calls = _native_calls(response.raw_output)
                if calls[0].name not in offered:
                    raise ValueError("tool was not offered in this request")
                parse_action(calls[0])
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                audit["error"] = type(exc).__name__
                attempts.append(audit)
                self.audit.append(audit)
                continue
            self.audit.append(audit)
            return ModelOutput(
                tool_calls=calls,
                prompt_tokens=response.prompt_tokens,
                completion_tokens=response.completion_tokens,
                latency_ms=response.latency_ms,
                finish_reason=response.finish_reason,
                model=response.model,
                checkpoint=response.checkpoint,
                seed_supported=response.seed_supported,
                cost=response.cost or Decimal(0),
                cost_known=response.cost is not None,
                raw_output_hash=raw_hash,
                retry_count=retry,
            )
        raise MalformedModelOutput(tuple(attempts))


def render_messages(task: TaskSpec, history: tuple, memory_examples: tuple = ()) -> tuple[Message, ...]:
    """The exact conversation a model policy sees before its next call (also used to rebuild rollout prompts)."""
    messages: list[Message] = []
    for episode in memory_examples:
        messages.append(
            Message(
                role="assistant",
                content=json.dumps(
                    {
                        "retrieved_episode_id": episode.episode_id,
                        "recommended_products": episode.recommended_products,
                        "termination": episode.termination,
                        "final_answer": episode.final_answer,
                    },
                    sort_keys=True,
                ),
            )
        )
    messages.append(Message(role="user", content=task.raw_message))
    for record in history:
        messages.append(
            Message(
                role="assistant",
                tool_name=record.action.type,
                tool_arguments=record.arguments,
            )
        )
        messages.append(
            Message(
                role="tool",
                tool_name=record.action.type,
                tool_result={
                    "references": record.result_references,
                    "summary": record.result_summary,
                    "error_code": record.error_code,
                },
            )
        )
    return tuple(messages)


class AdapterPolicy(ActionPolicy):
    """Translate runner history into a structured model request and typed action."""

    def __init__(self, adapter: ModelAdapter, system_prompt: str, *, seed: int | None = None,
                 request_id: str | None = None, temperature: Decimal = Decimal("0"), checkpoint: str | None = None):
        self.adapter = adapter
        self.system_prompt = system_prompt
        self.seed = seed
        self.request_id = request_id
        self.temperature = temperature
        self.checkpoint = checkpoint
        self.memory_examples = ()

    def accept_memory(self, episodes: tuple) -> None:
        self.memory_examples = episodes

    def next_step(self, task: TaskSpec, history: tuple, attempt: int) -> ModelStep | None:
        messages = render_messages(task, history, self.memory_examples)
        request = ModelRequest(
            request_id=self.request_id or task.id,
            sequence=len(history),
            system_prompt=self.system_prompt,
            messages=messages,
            tools=action_tools(),
            seed=self.seed,
            temperature=self.temperature,
            checkpoint=self.checkpoint,
        )
        output = self.adapter.generate(request)
        if output.malformed or len(output.tool_calls) != 1:
            raise MalformedModelOutput((output.metadata(),))
        action = parse_action(output.tool_calls[0])
        return ModelStep(
            action=action,
            token_count=output.prompt_tokens + output.completion_tokens,
            cost=output.cost,
            metadata=output.metadata(),
        )
