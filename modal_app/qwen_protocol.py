"""Wire contract between the runtime inference client and the Modal Qwen server (no `modal` import: usable anywhere).

Requests carry only chat messages, tool schemas, sampling controls and the pinned revision. The server never executes
anything it is sent; it renders the chat template and generates text."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from modal_app.qwen_toolcalls import MODEL_ID, MODEL_REVISION

MAX_NEW_TOKENS_CEILING = 512
MAX_MESSAGES = 200


class QwenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    system: str = Field(min_length=1)
    messages: list[dict[str, object]] = Field(max_length=MAX_MESSAGES)
    tools: list[dict[str, object]] = Field(min_length=1)
    seed: int = Field(ge=0, lt=2**32)
    temperature: float = Field(ge=0, le=2)
    max_new_tokens: int = Field(ge=1, le=MAX_NEW_TOKENS_CEILING)
    model: str = MODEL_ID
    revision: str = MODEL_REVISION


class QwenResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    raw_output: str
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    finish_reason: str = Field(min_length=1)  # "stop" (EOS) or "length" (max_new_tokens reached)
    model: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    seed_applied: bool
    generation_seconds: float = Field(ge=0)
    container_load_seconds: float = Field(default=0, ge=0)  # >0 only for the first request a container serves
