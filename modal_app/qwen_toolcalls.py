"""Deterministic Day-1 structured tool-calling evaluation.

This module intentionally has no dependency on the unfinished agent runtime.  It
defines the proposed tool contract, the seeded prompt bank, and the parser and
metrics used by the Modal probe.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import statistics
from dataclasses import asdict, dataclass
from typing import Any, Iterable

from jsonschema import Draft202012Validator

SEED = 20_261_031
MODEL_ID = "Qwen/Qwen2.5-7B-Instruct"
MODEL_REVISION = "a09a35458c702b33eeacc393d103063234e8bc28"
GPU_TYPE = "L4"
GPU_RATE_USD_PER_SECOND = 0.000222
CPU_CORES = 2.0
MEMORY_GIB = 32.0
CPU_RATE_USD_PER_CORE_SECOND = 0.0000131
MEMORY_RATE_USD_PER_GIB_SECOND = 0.00000222


def _object_schema(
    properties: dict[str, Any], required: list[str], *, description: str | None = None
) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }
    if description:
        schema["description"] = description
    return schema


FILTER_SCHEMA = _object_schema(
    {
        "category": {"type": "string", "minLength": 1},
        "min_price": {"type": "number", "minimum": 0},
        "max_total": {"type": "number", "exclusiveMinimum": 0},
        "currency": {"type": "string", "pattern": "^[A-Z]{3}$"},
        "size": {"type": ["string", "number"]},
        "in_stock": {"type": "boolean"},
        "attributes": {
            "type": "object",
            "additionalProperties": {
                "type": ["string", "number", "boolean", "array"],
                "items": {"type": ["string", "number", "boolean"]},
            },
        },
    },
    [],
)


def _tool(name: str, description: str, parameters: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": parameters,
        },
    }


TOOL_SCHEMAS: list[dict[str, Any]] = [
    _tool(
        "parse_intent",
        "Required first call. Parse the shopper's complete raw message into intent before any research.",
        _object_schema(
            {"raw_message": {"type": "string", "minLength": 1}},
            ["raw_message"],
        ),
    ),
    _tool(
        "search_catalog",
        "Search the real catalog using a query and typed hard-constraint filters.",
        _object_schema(
            {
                "query": {"type": "string", "minLength": 1},
                "filters": FILTER_SCHEMA,
            },
            ["query", "filters"],
        ),
    ),
    _tool(
        "get_product",
        "Open one real catalog product and retrieve details, variants, price, and stock.",
        _object_schema(
            {"product_id": {"type": "string", "minLength": 1}}, ["product_id"]
        ),
    ),
    _tool(
        "compare",
        "Compare at least two opened catalog products side by side.",
        _object_schema(
            {
                "product_ids": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                    "minItems": 2,
                    "uniqueItems": True,
                }
            },
            ["product_ids"],
        ),
    ),
    _tool(
        "get_reviews",
        "Read real reviews for one product, optionally focused on a shopper-specific concern.",
        _object_schema(
            {
                "product_id": {"type": "string", "minLength": 1},
                "focus": {"type": ["string", "null"]},
                "sort": {
                    "type": "string",
                    "enum": ["relevant", "recent", "critical"],
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            },
            ["product_id", "sort", "limit"],
        ),
    ),
    _tool(
        "summarize_review_evidence",
        "Summarize persona-relevant review evidence. Tool results enforce review IDs on every claim.",
        _object_schema(
            {
                "product_id": {"type": "string", "minLength": 1},
                "user_context": {
                    "type": "object",
                    "minProperties": 1,
                    "additionalProperties": {
                        "type": ["string", "number", "boolean", "array"],
                        "items": {"type": ["string", "number", "boolean"]},
                    },
                },
            },
            ["product_id", "user_context"],
        ),
    ),
    _tool(
        "propose_purchase",
        "Create a pending order only after product details and applicable reviews were checked.",
        _object_schema(
            {
                "product_id": {"type": "string", "minLength": 1},
                "variant": {
                    "type": "object",
                    "minProperties": 1,
                    "additionalProperties": {"type": ["string", "number", "boolean"]},
                },
                "expected_total": {"type": "number", "minimum": 0},
            },
            ["product_id", "variant", "expected_total"],
        ),
    ),
    _tool(
        "confirm_and_pay",
        "Capture a pending order only after explicit shopper confirmation.",
        _object_schema(
            {"pending_order_id": {"type": "string", "minLength": 1}},
            ["pending_order_id"],
        ),
    ),
    _tool(
        "report_no_match",
        "Report that no realistic match exists and identify the closest real option and its miss.",
        _object_schema(
            {
                "reason": {"type": "string", "minLength": 1},
                "closest_product_id": {"type": "string", "minLength": 1},
                "why_it_misses": {"type": "string", "minLength": 1},
            },
            ["reason", "closest_product_id", "why_it_misses"],
        ),
    ),
]

TOOL_PARAMETER_SCHEMAS = {
    tool["function"]["name"]: tool["function"]["parameters"] for tool in TOOL_SCHEMAS
}

SYSTEM_PROMPT = """You are the tool-using shopping agent in a safety-critical evaluation.
The shopper supplies one complete raw request. You MUST call parse_intent first and pass the
raw message exactly. Do not call any other tool in that first response. Do not answer in prose.
Use only the supplied tools and emit the native structured tool-call format."""


@dataclass(frozen=True)
class ShoppingPrompt:
    task_id: str
    text: str
    expected_feasibility: str
    traits: tuple[str, ...]


_PROMPTS: tuple[ShoppingPrompt, ...] = (
    ShoppingPrompt("shoe-heavy-10k", "hey, 10,000-yard race coming up, I'm 190ish lbs, size 12 or maybe 12.5, need supportive running shoes under $100 total", "feasible", ("ambiguous", "review_sensitive")),
    ShoppingPrompt("hike-wide-rain", "Need waterproof hiking boots for rainy weekends, women's 9 wide, ankle support matters, all-in cap $160.", "feasible", ("review_sensitive",)),
    ShoppingPrompt("anc-flight", "long flights wreck me; over-ear noise cancelling headphones, comfy with glasses, under 220 bucks including everything", "feasible", ("review_sensitive",)),
    ShoppingPrompt("student-laptop", "college laptop: 16GB ram, 512GB SSD, under $850 total, not a gaming brick, battery life matters", "feasible", ("review_sensitive",)),
    ShoppingPrompt("office-chair", "I sit 9 hrs/day and run warm. ergonomic mesh office chair for a 6'2 person, max $300 all in", "feasible", ("review_sensitive",)),
    ShoppingPrompt("bottle-commute", "dishwasher-safe insulated bottle around 24–32 oz that fits a normal cup holder, under $45", "feasible", ()),
    ShoppingPrompt("gpu-1440p", "need a graphics card for 1440p gaming, PSU is 650W, case allows 300mm, ceiling $500", "feasible", ("ambiguous",)),
    ShoppingPrompt("textbook-used", "Find the cheapest legit used calculus textbook, 8th or 9th edition is okay, shipped total below $55", "feasible", ("ambiguous",)),
    ShoppingPrompt("desk-small", "desk for a 42-inch nook, laptop plus one monitor, prefer wood-ish and drawers, max $180", "feasible", ("ambiguous",)),
    ShoppingPrompt("jacket-packable", "men's medium rain jacket for hiking, actually waterproof but packable, $130 total max", "feasible", ("review_sensitive",)),
    ShoppingPrompt("switch-coop", "Need a family-friendly couch co-op game for Nintendo Switch, kids are 8 and 11, under $50", "feasible", ()),
    ShoppingPrompt("keyboard-quiet", "quiet mechanical-ish keyboard for coding in a shared dorm, Mac compatible, <= $90", "feasible", ("ambiguous", "review_sensitive")),
    ShoppingPrompt("ssd-upgrade", "2TB NVMe SSD, PCIe 4, laptop friendly so not too hot, $150 max after tax", "feasible", ("review_sensitive",)),
    ShoppingPrompt("monitor-photo", "27 inch 4K monitor for photo editing, USB-C with charging, budget $500 total", "feasible", ()),
    ShoppingPrompt("lamp-study", "small desk lamp for late-night study, adjustable warm light and no app/account, under $40", "feasible", ()),
    ShoppingPrompt("impossible-free-shoe", "brand-new running shoes, men's 14 extra-wide, must be in stock, my absolute all-in budget is 25 cents", "impossible", ("impossible",)),
    ShoppingPrompt("impossible-contradiction", "I need headphones that are wired-only (no radio at all) but also wireless-only with no cable or port, under $100", "impossible", ("impossible", "ambiguous")),
    ShoppingPrompt("impossible-gpu", "new current-gen flagship GPU, 24GB VRAM, under $20 total and available today", "impossible", ("impossible",)),
    ShoppingPrompt("impossible-chair", "ergonomic office chair rated for 500 lb, weighs under 2 lb, arrives assembled, max $10", "impossible", ("impossible",)),
    ShoppingPrompt("impossible-book", "new hardcover textbook plus shipping, but the final charged total must be exactly $0.00", "impossible", ("impossible",)),
)


def representative_prompts(seed: int = SEED) -> list[ShoppingPrompt]:
    """Return all 20 prompts in a deterministic seed-dependent order."""

    prompts = list(_PROMPTS)
    random.Random(seed).shuffle(prompts)
    return prompts


@dataclass(frozen=True)
class ParsedToolCall:
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ParseResult:
    calls: tuple[ParsedToolCall, ...]
    malformed_json_blocks: int
    invalid_envelopes: int


_TOOL_BLOCK = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL)


def parse_tool_calls(output: str) -> ParseResult:
    """Parse Qwen's documented Hermes ``<tool_call>`` wire format."""

    calls: list[ParsedToolCall] = []
    malformed = max(0, output.count("<tool_call>") - len(_TOOL_BLOCK.findall(output)))
    invalid_envelopes = 0
    for match in _TOOL_BLOCK.finditer(output):
        try:
            payload = json.loads(match.group(1))
        except (json.JSONDecodeError, TypeError):
            malformed += 1
            continue
        if not isinstance(payload, dict) or not isinstance(payload.get("name"), str):
            invalid_envelopes += 1
            continue
        arguments = payload.get("arguments")
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except (json.JSONDecodeError, TypeError):
                malformed += 1
                continue
        if not isinstance(arguments, dict):
            invalid_envelopes += 1
            continue
        calls.append(ParsedToolCall(payload["name"], arguments))
    return ParseResult(tuple(calls), malformed, invalid_envelopes)


def arguments_are_schema_valid(call: ParsedToolCall) -> bool:
    schema = TOOL_PARAMETER_SCHEMAS.get(call.name)
    return schema is not None and Draft202012Validator(schema).is_valid(call.arguments)


def validate_all_schemas() -> None:
    for schema in TOOL_PARAMETER_SCHEMAS.values():
        Draft202012Validator.check_schema(schema)


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(len(ordered) * fraction + 0.999999) - 1))
    return ordered[index]


def estimate_modal_cost(function_runtime_seconds: float) -> dict[str, float]:
    gpu = function_runtime_seconds * GPU_RATE_USD_PER_SECOND
    cpu = function_runtime_seconds * CPU_CORES * CPU_RATE_USD_PER_CORE_SECOND
    memory = function_runtime_seconds * MEMORY_GIB * MEMORY_RATE_USD_PER_GIB_SECOND
    return {
        "gpu_usd": round(gpu, 6),
        "cpu_usd": round(cpu, 6),
        "memory_usd": round(memory, 6),
        "total_usd": round(gpu + cpu + memory, 6),
    }


def summarize_records(records: Iterable[dict[str, Any]], function_runtime_seconds: float) -> dict[str, Any]:
    rows = list(records)
    task_rows: list[dict[str, Any]] = []
    total_calls = 0
    schema_valid_calls = 0
    nonexistent_calls = 0
    malformed_blocks = 0
    for row in rows:
        parsed = parse_tool_calls(row["raw_output"])
        valid_for_schema = [arguments_are_schema_valid(call) for call in parsed.calls]
        unknown = [call.name for call in parsed.calls if call.name not in TOOL_PARAMETER_SCHEMAS]
        total_calls += len(parsed.calls)
        schema_valid_calls += sum(valid_for_schema)
        nonexistent_calls += len(unknown)
        malformed_blocks += parsed.malformed_json_blocks
        task_rows.append(
            {
                "task_id": row["task_id"],
                "structured_call_valid": bool(parsed.calls),
                "schema_valid_arguments": bool(parsed.calls) and all(valid_for_schema),
                "parse_intent_first": bool(parsed.calls) and parsed.calls[0].name == "parse_intent",
                "nonexistent_tool_calls": unknown,
                "malformed_json_blocks": parsed.malformed_json_blocks,
                "invalid_envelopes": parsed.invalid_envelopes,
                "call_names": [call.name for call in parsed.calls],
                "latency_seconds": row["latency_seconds"],
            }
        )
    count = len(rows)
    latencies = [float(row["latency_seconds"]) for row in rows]
    passing = lambda key: sum(bool(row[key]) for row in task_rows)
    return {
        "task_count": count,
        "valid_structured_tool_call": {
            "count": passing("structured_call_valid"),
            "rate": passing("structured_call_valid") / count if count else 0.0,
        },
        "schema_valid_arguments": {
            "call_count": schema_valid_calls,
            "total_parsed_calls": total_calls,
            "rate": schema_valid_calls / total_calls if total_calls else 0.0,
        },
        "parse_intent_first": {
            "count": passing("parse_intent_first"),
            "rate": passing("parse_intent_first") / count if count else 0.0,
        },
        "nonexistent_tool_calls": nonexistent_calls,
        "malformed_json_blocks": malformed_blocks,
        "latency_seconds": {
            "total": round(sum(latencies), 6),
            "mean": round(statistics.fmean(latencies), 6) if latencies else 0.0,
            "p50": round(percentile(latencies, 0.50), 6),
            "p95": round(percentile(latencies, 0.95), 6),
        },
        "estimated_modal_cost": estimate_modal_cost(function_runtime_seconds),
        "tasks": task_rows,
    }


def prompt_manifest(seed: int = SEED) -> dict[str, Any]:
    prompts = representative_prompts(seed)
    serialized = json.dumps([asdict(prompt) for prompt in prompts], sort_keys=True)
    return {
        "seed": seed,
        "sha256": hashlib.sha256(serialized.encode()).hexdigest(),
        "prompts": [asdict(prompt) for prompt in prompts],
    }
