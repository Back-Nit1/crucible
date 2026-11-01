import json
from decimal import Decimal

import pytest

from scoring.judge import ConfiguredJudgeAdapter, JudgeInvocation, input_hash


PAYLOAD = {
    "criterion": "Does the assumption follow from the shopper message?",
    "shopper_context": "Need quiet headphones for a shared office.",
    "candidate": "Assumes low audible switch noise matters.",
    "evidence": ["shopper explicitly says quiet", "shared office"],
}


def test_configured_judge_is_pinned_hashed_cached_and_structured():
    calls = []

    def invoke(model, prompt, payload, retry):
        calls.append((model, prompt, payload, retry))
        return JudgeInvocation(
            raw_output=json.dumps({
                "score": "0.75",
                "rationale": "The assumption is directly supported.",
                "deterministic_disagreement": True,
                "disagreement_detail": "Catalog attribute was unavailable.",
            }),
            latency_ms=12,
            cost=Decimal("0.002"),
        )

    judge = ConfiguredJudgeAdapter(
        model="fixed-judge-checkpoint",
        prompt_version="semantic-v1",
        invoker=invoke,
    )
    first = judge.evaluate("semantic-v1", PAYLOAD)
    second = judge.evaluate("semantic-v1", PAYLOAD)
    assert first == second and len(calls) == 1
    assert first.input_hash == input_hash(PAYLOAD)
    assert first.cache_key == f"fixed-judge-checkpoint:semantic-v1:{first.input_hash}"
    assert first.output["score"] == "0.75"
    assert first.deterministic_disagreement
    assert first.latency_ms == 12 and first.cost == Decimal("0.002")


def test_unconfigured_and_malformed_judges_fail_closed_and_cache_failure():
    unconfigured = ConfiguredJudgeAdapter(model="pinned", prompt_version="v1")
    result = unconfigured.evaluate("v1", PAYLOAD)
    assert result.parse_failed and result.output["score"] == "0" and result.attempts == 0

    calls = []

    def malformed(model, prompt, payload, retry):
        calls.append(retry)
        return JudgeInvocation(raw_output="not json", latency_ms=5, cost=Decimal("0.01"))

    judge = ConfiguredJudgeAdapter(
        model="pinned",
        prompt_version="v1",
        invoker=malformed,
        max_retries=1,
    )
    failed = judge.evaluate("v1", PAYLOAD)
    again = judge.evaluate("v1", PAYLOAD)
    assert failed == again and calls == [0, 1]
    assert failed.parse_failed and failed.output["score"] == "0"
    assert failed.attempts == 2 and failed.latency_ms == 10 and failed.cost == Decimal("0.02")


def test_judge_rejects_version_drift_and_hidden_evaluation_labels():
    judge = ConfiguredJudgeAdapter(model="pinned", prompt_version="v1")
    with pytest.raises(ValueError, match="pinned"):
        judge.evaluate("v2", PAYLOAD)
    with pytest.raises(ValueError, match="evaluation labels"):
        judge.evaluate("v1", {**PAYLOAD, "feasible_set": ["secret-answer"]})
