"""Auditable fixed-judge protocol; production adapters may cache but tests never call models."""

from __future__ import annotations

import hashlib
import json
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field


class JudgeResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    prompt_version: str = Field(min_length=1)
    input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output: dict[str, object]
    cache_key: str = Field(min_length=1)
    parse_failed: bool = False


class Judge(Protocol):
    def evaluate(self, prompt_version: str, payload: dict[str, object]) -> JudgeResult: ...


def input_hash(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


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
