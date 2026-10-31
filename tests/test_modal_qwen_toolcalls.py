import json

import pytest

from modal_app.qwen_toolcalls import (
    MODEL_REVISION,
    ParsedToolCall,
    arguments_are_schema_valid,
    estimate_modal_cost,
    parse_tool_calls,
    prompt_manifest,
    representative_prompts,
    summarize_records,
    validate_all_schemas,
)


def tool_block(name: str, arguments: object) -> str:
    return f"<tool_call>\n{json.dumps({'name': name, 'arguments': arguments})}\n</tool_call>"


def test_all_tool_schemas_are_valid_draft_2020_12() -> None:
    validate_all_schemas()


def test_prompt_bank_is_seeded_complete_and_balanced() -> None:
    prompts = representative_prompts()
    assert len(prompts) == 20
    assert len({prompt.task_id for prompt in prompts}) == 20
    assert sum(prompt.expected_feasibility == "impossible" for prompt in prompts) == 5
    assert sum("review_sensitive" in prompt.traits for prompt in prompts) >= 4
    assert sum("ambiguous" in prompt.traits for prompt in prompts) >= 4
    assert representative_prompts() == prompts
    assert representative_prompts(1) != prompts


def test_prompt_manifest_is_stable() -> None:
    first = prompt_manifest()
    second = prompt_manifest()
    assert first == second
    assert len(first["sha256"]) == 64


def test_exact_model_revision_is_full_commit_hash() -> None:
    assert len(MODEL_REVISION) == 40
    int(MODEL_REVISION, 16)


def test_parser_accepts_documented_qwen_tool_format() -> None:
    result = parse_tool_calls(tool_block("parse_intent", {"raw_message": "need shoes"}))
    assert result.calls == (ParsedToolCall("parse_intent", {"raw_message": "need shoes"}),)
    assert result.malformed_json_blocks == 0
    assert result.invalid_envelopes == 0


def test_parser_accepts_string_encoded_arguments() -> None:
    result = parse_tool_calls(tool_block("get_product", json.dumps({"product_id": "p1"})))
    assert result.calls[0].arguments == {"product_id": "p1"}


@pytest.mark.parametrize(
    "output",
    [
        "<tool_call>\n{broken}\n</tool_call>",
        '<tool_call>\n{"name":"parse_intent","arguments":"{broken}"}\n</tool_call>',
        '<tool_call>\n{"name":"parse_intent","arguments": {"raw_message":"x"}}',
    ],
)
def test_parser_counts_malformed_json_and_unclosed_blocks(output: str) -> None:
    result = parse_tool_calls(output)
    assert not result.calls
    assert result.malformed_json_blocks == 1


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"arguments": {}},
        {"name": 3, "arguments": {}},
        {"name": "parse_intent", "arguments": []},
    ],
)
def test_parser_rejects_invalid_envelopes(payload: object) -> None:
    result = parse_tool_calls(f"<tool_call>\n{json.dumps(payload)}\n</tool_call>")
    assert not result.calls
    assert result.invalid_envelopes == 1


def test_schema_validation_rejects_extra_and_missing_arguments() -> None:
    assert arguments_are_schema_valid(ParsedToolCall("parse_intent", {"raw_message": "x"}))
    assert not arguments_are_schema_valid(ParsedToolCall("parse_intent", {}))
    assert not arguments_are_schema_valid(
        ParsedToolCall("parse_intent", {"raw_message": "x", "extra": True})
    )
    assert not arguments_are_schema_valid(ParsedToolCall("invented", {}))


def test_metrics_are_deterministic_and_use_clear_denominators() -> None:
    records = [
        {
            "task_id": "ok",
            "raw_output": tool_block("parse_intent", {"raw_message": "x"}),
            "latency_seconds": 1.0,
        },
        {
            "task_id": "unknown",
            "raw_output": tool_block("made_up", {}),
            "latency_seconds": 2.0,
        },
        {
            "task_id": "malformed",
            "raw_output": "<tool_call>\n{broken}\n</tool_call>",
            "latency_seconds": 3.0,
        },
    ]
    summary = summarize_records(records, function_runtime_seconds=10.0)
    assert summary["valid_structured_tool_call"] == {"count": 2, "rate": 2 / 3}
    assert summary["schema_valid_arguments"] == {
        "call_count": 1,
        "total_parsed_calls": 2,
        "rate": 0.5,
    }
    assert summary["parse_intent_first"] == {"count": 1, "rate": 1 / 3}
    assert summary["nonexistent_tool_calls"] == 1
    assert summary["malformed_json_blocks"] == 1
    assert summary["latency_seconds"]["p50"] == 2.0
    assert summary["latency_seconds"]["p95"] == 3.0


def test_cost_estimate_includes_gpu_cpu_and_memory() -> None:
    estimate = estimate_modal_cost(3_600)
    assert estimate["gpu_usd"] == pytest.approx(0.7992)
    assert estimate["total_usd"] > estimate["gpu_usd"]
    assert estimate["total_usd"] < 5
