from scoring.judge import ConfiguredJudgeAdapter, input_hash


def test_unconfigured_judge_fails_closed_without_external_call():
    result = ConfiguredJudgeAdapter(prompt_version="judge-v1").evaluate(
        "judge-v1", {"claim": "fixture"})
    assert result.parse_failed
    assert result.output == {"score": "0", "error": "judge_not_configured"}
    assert result.cache_key == f"judge-v1:{input_hash({'claim': 'fixture'})}"


def test_configured_boundary_hashes_parses_and_caches_once():
    calls = []
    def invoke(version, payload):
        calls.append((version, payload))
        return '{"score": "1", "reason": "fixture"}'
    import json
    judge = ConfiguredJudgeAdapter(prompt_version="judge-v2", invoker=invoke, parser=json.loads)
    first = judge.evaluate("judge-v2", {"b": 2, "a": 1})
    second = judge.evaluate("judge-v2", {"a": 1, "b": 2})
    assert first is second and len(calls) == 1
    assert not first.parse_failed and first.output["score"] == "1"


def test_malformed_output_and_version_mismatch_fail_closed():
    judge = ConfiguredJudgeAdapter(prompt_version="judge-v1", invoker=lambda *_: "bad",
                                   parser=lambda _: (_ for _ in ()).throw(ValueError("bad")))
    assert judge.evaluate("judge-v1", {}).output["score"] == "0"
    mismatch = judge.evaluate("judge-v0", {})
    assert mismatch.parse_failed and mismatch.output["error"] == "prompt_version_mismatch"
