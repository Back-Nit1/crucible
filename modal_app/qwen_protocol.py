"""Wire contract between the runtime inference client and the Modal Qwen server (no `modal` import: usable anywhere).

Requests carry only chat messages, tool schemas, sampling controls and the pinned revision. The server never executes
anything it is sent; it renders the chat template and generates text."""
from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict, Field, model_validator

from modal_app.adapter_artifact import HEX64, RUN_ID_PATTERN, AdapterSelection
from modal_app.qwen_toolcalls import MODEL_ID, MODEL_REVISION

MAX_NEW_TOKENS_CEILING = 512
MAX_MESSAGES = 200
MAX_INPUT_CHARS = 200_000   # cheap pre-tokenization bound on system + messages + tools
MAX_INPUT_TOKENS = 8192     # enforced after tokenization; 7B bf16 weights (15.2 GB) + this KV cache fit an L4 (24 GB)


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
    # Optional LoRA adapter selection. Absent = the pinned base model (the original contract, unchanged on the wire).
    # Present = serve exactly that verified adapter or reject: the server never falls back to the base model.
    adapter: AdapterSelection | None = None

    @model_validator(mode="after")
    def _bounded_input(self) -> "QwenRequest":
        if len(json.dumps([self.system, self.messages, self.tools], default=str)) > MAX_INPUT_CHARS:
            raise ValueError("request exceeds the input size bound")
        return self


class QwenResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    raw_output: str
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    finish_reason: str = Field(min_length=1)  # "stop" (EOS) or "length" (max_new_tokens reached)
    model: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    seed_applied: bool
    generation_seconds: float = Field(ge=0)  # wall time of the engine call that produced this output (true latency)
    batch_size: int = Field(default=1, ge=1)  # requests sharing that call: GPU cost is generation_seconds / batch_size each
    container_load_seconds: float = Field(default=0, ge=0)  # >0 only for the first request a container serves
    # Identity of the adapter that produced this output; all None for the base model (and omitted on the wire).
    adapter_run_id: str | None = Field(default=None, pattern=RUN_ID_PATTERN)
    adapter_hash: str | None = Field(default=None, pattern=HEX64)
    training_manifest_hash: str | None = Field(default=None, pattern=HEX64)
    adapter_load_seconds: float = Field(default=0, ge=0)  # >0 only on the request that loaded the adapter


class QwenRejection(BaseModel):
    """Structured refusal returned (not raised) before any generation, so the client sees a stable code instead of an
    opaque remote exception. Never carries request text."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    error_code: str = Field(min_length=1)
    detail: str = Field(default="", max_length=200)
