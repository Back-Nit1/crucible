"""Auditable fixed-judge protocol; production adapters may cache but tests never call models."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Callable, Protocol

from pydantic import BaseModel, ConfigDict, Field


class JudgeResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    prompt_version: str = Field(min_length=1)
    input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output: dict[str, object]
    cache_key: str = Field(min_length=1)
    parse_failed: bool = False
    model: str = Field(default="deterministic-fake", min_length=1)
    attempts: int = Field(default=1, ge=0)
    latency_ms: int = Field(default=0, ge=0)
    cost: Decimal = Field(default=Decimal("0"), ge=0)
    deterministic_disagreement: bool = False
    disagreement_detail: str | None = None


class Judge(Protocol):
    def evaluate(self, prompt_version: str, payload: dict[str, object]) -> JudgeResult: ...


def input_hash(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


class SemanticJudgeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    score: Decimal = Field(ge=0, le=1)
    rationale: str = Field(min_length=1)
    deterministic_disagreement: bool = False
    disagreement_detail: str | None = None


class JudgeInvocation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    raw_output: str
    latency_ms: int = Field(ge=0)
    cost: Decimal = Field(default=Decimal("0"), ge=0)


JudgeInvoker = Callable[[str, str, dict[str, object], int], JudgeInvocation]
_FORBIDDEN_LABEL_FIELDS = {
    "best_value_reference",
    "feasible_set",
    "is_impossible",
    "review_adjusted_best",
    "split",
    "test_label",
}


class ConfiguredJudgeAdapter:
    """Pinned, cached judge adapter; no client is constructed implicitly."""

    def __init__(
        self,
        *,
        model: str,
        prompt_version: str,
        invoker: JudgeInvoker | None = None,
        max_retries: int = 1,
    ) -> None:
        if not model or not prompt_version:
            raise ValueError("judge model and prompt version must be pinned")
        if max_retries < 0 or max_retries > 2:
            raise ValueError("judge max_retries must be between zero and two")
        self.model = model
        self.prompt_version = prompt_version
        self.invoker = invoker
        self.max_retries = max_retries
        self.cache: dict[str, JudgeResult] = {}

    def evaluate(self, prompt_version: str, payload: dict[str, object]) -> JudgeResult:
        if prompt_version != self.prompt_version:
            raise ValueError("judge prompt version does not match pinned configuration")
        forbidden = sorted(_FORBIDDEN_LABEL_FIELDS & set(payload))
        if forbidden:
            raise ValueError(f"judge payload contains evaluation labels: {forbidden}")
        digest = input_hash(payload)
        key = f"{self.model}:{self.prompt_version}:{digest}"
        if key in self.cache:
            return self.cache[key]
        if self.invoker is None:
            result = self._failed(digest, key, attempts=0, latency_ms=0, cost=Decimal(0), error="judge not configured")
            self.cache[key] = result
            return result

        total_latency = 0
        total_cost = Decimal(0)
        last_error = "malformed structured output"
        for retry in range(self.max_retries + 1):
            try:
                invocation = self.invoker(self.model, self.prompt_version, payload, retry)
                total_latency += invocation.latency_ms
                total_cost += invocation.cost
                parsed = SemanticJudgeOutput.model_validate_json(invocation.raw_output)
            except Exception as exc:
                last_error = type(exc).__name__
                continue
            result = JudgeResult(
                prompt_version=self.prompt_version,
                input_hash=digest,
                output=parsed.model_dump(mode="json"),
                cache_key=key,
                model=self.model,
                attempts=retry + 1,
                latency_ms=total_latency,
                cost=total_cost,
                deterministic_disagreement=parsed.deterministic_disagreement,
                disagreement_detail=parsed.disagreement_detail,
            )
            self.cache[key] = result
            return result
        result = self._failed(
            digest,
            key,
            attempts=self.max_retries + 1,
            latency_ms=total_latency,
            cost=total_cost,
            error=last_error,
        )
        self.cache[key] = result
        return result

    def _failed(
        self,
        digest: str,
        key: str,
        *,
        attempts: int,
        latency_ms: int,
        cost: Decimal,
        error: str,
    ) -> JudgeResult:
        return JudgeResult(
            prompt_version=self.prompt_version,
            input_hash=digest,
            output={"score": "0", "error": error},
            cache_key=key,
            parse_failed=True,
            model=self.model,
            attempts=attempts,
            latency_ms=latency_ms,
            cost=cost,
        )


class DeterministicFakeJudge:
    def __init__(self, outputs: dict[str, dict[str, object]], *, fail_closed: bool = True):
        self.outputs = outputs
        self.fail_closed = fail_closed
        self.cache: dict[str, JudgeResult] = {}

    def evaluate(self, prompt_version: str, payload: dict[str, object]) -> JudgeResult:
        digest = input_hash(payload)
        key = f"{prompt_version}:{digest}"
        if key in self.cache:
            return self.cache[key]
        output = self.outputs.get(key)
        failed = output is None
        if failed:
            output = {"score": "0" if self.fail_closed else None, "error": "unconfigured fixture"}
        result = JudgeResult(prompt_version=prompt_version, input_hash=digest, output=output,
                             cache_key=key, parse_failed=failed)
        self.cache[key] = result
        return result
