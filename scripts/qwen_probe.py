"""Bounded Qwen tool-calling probe: exactly the 20 seeded prompts, one first turn each, through the production
adapter/client stack (ModalQwenClient -> QwenModelAdapter). Refuses to start without launch authorization.

  uv run python -m scripts.qwen_probe --env-file <.env> [--out docs/spikes/results/qwen_probe]

Requires the user to have: rotated the Modal token, added a payment method, deployed modal_app/qwen_inference.py with
CRUCIBLE_ENABLE_L4_PROBE=1, and exported CRUCIBLE_MODAL_TOKEN_ROTATED=1, CRUCIBLE_MODAL_BILLING_CONFIRMED=1 and
CRUCIBLE_MODAL_APPROVED_CEILING_USD=<approved>. Artifacts hold hashes, counts and codes only: never raw model output.

Quality threshold (this probe's pass bar, proposed here because no numeric bar was previously documented):
  valid structured call >= 90% of 20, schema-valid arguments >= 90% of parsed calls, parse_intent first >= 90% of 20,
  zero calls to tools that were not offered. Anything below is reported as FAIL and the model is not promoted."""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from decimal import Decimal
from pathlib import Path

from agents.model import (InferenceError, MalformedModelOutput, Message, ModelAdapter, ModelRequest, QwenModelAdapter,
                          action_tools, parse_action)
from modal_app.qwen_toolcalls import MODEL_ID, MODEL_REVISION, SEED, SYSTEM_PROMPT, prompt_manifest, representative_prompts

THRESHOLDS = {"valid_structured_call": 0.90, "schema_valid_arguments": 0.90, "parse_intent_first": 0.90}
KEYS = {"CRUCIBLE_MODAL_TOKEN_ROTATED", "CRUCIBLE_MODAL_BILLING_CONFIRMED", "CRUCIBLE_MODAL_APPROVED_CEILING_USD"}


def _rate(n: int, d: int) -> dict:
    return {"numerator": n, "denominator": d, "value": None if not d else round(n / d, 4)}


def _pct(values: list[float], q: float) -> float | None:
    return sorted(values)[min(len(values) - 1, int(q * len(values)))] if values else None


def run_probe(adapter: ModelAdapter, *, temperature: str = "0") -> dict:
    prompts = representative_prompts(SEED)
    rows = []
    for i, prompt in enumerate(prompts):
        request = ModelRequest(
            request_id=f"probe:{prompt.task_id}", sequence=0, system_prompt=SYSTEM_PROMPT, seed=SEED + i,
            messages=(Message(role="user", content=prompt.text),), tools=action_tools(),
            temperature=Decimal(temperature), checkpoint="qwen-base")
        row = {"task_id": prompt.task_id, "expected_feasibility": prompt.expected_feasibility, "traits": list(prompt.traits)}
        try:
            out = adapter.generate(request)
            call = out.tool_calls[0]
            row |= {"outcome": "valid", "tool": call.name, "schema_valid": True, "parse_intent_first": call.name == "parse_intent",
                    "prompt_tokens": out.prompt_tokens, "completion_tokens": out.completion_tokens, "latency_ms": out.latency_ms,
                    "retry_count": out.retry_count, "finish_reason": out.finish_reason, "cost": str(out.cost),
                    "cost_known": out.cost_known, "raw_output_hash": out.raw_output_hash}
        except MalformedModelOutput as exc:
            row |= {"outcome": "malformed", "attempts": len(exc.attempts), "retry_count": len(exc.attempts) - 1,
                    "raw_output_hashes": [a.get("raw_output_hash") for a in exc.attempts],
                    "error_types": [a.get("error") for a in exc.attempts]}
        except InferenceError as exc:
            row |= {"outcome": "inference_error", "error_code": exc.code, "retryable": exc.retryable}
        rows.append(row)
    valid = [r for r in rows if r["outcome"] == "valid"]
    lat = [float(r["latency_ms"]) for r in valid]
    metrics = {
        "valid_structured_call": _rate(len(valid), len(rows)),
        "schema_valid_arguments": _rate(sum(r["schema_valid"] for r in valid), len(valid)),
        "parse_intent_first": _rate(sum(r["parse_intent_first"] for r in valid), len(rows)),
        "malformed": _rate(sum(r["outcome"] == "malformed" for r in rows), len(rows)),
        "inference_errors": _rate(sum(r["outcome"] == "inference_error" for r in rows), len(rows)),
        "retries": sum(r.get("retry_count", 0) for r in rows),
        "tokens": {"prompt": sum(r.get("prompt_tokens", 0) for r in valid), "completion": sum(r.get("completion_tokens", 0) for r in valid)},
        "latency_ms": {"mean": round(statistics.fmean(lat), 1) if lat else None, "p50": _pct(lat, .5), "p95": _pct(lat, .95),
                       "max": max(lat) if lat else None, "measured_over": len(lat)},
        "cost_usd": {"total": str(sum((Decimal(r["cost"]) for r in valid), Decimal(0))),
                     "per_prompt": str(sum((Decimal(r["cost"]) for r in valid), Decimal(0)) / len(rows)),
                     "all_known": all(r["cost_known"] for r in valid), "basis": "generation-seconds x Modal list rates (estimate)"},
    }
    passed = (len(valid) > 0 and all(
        (metrics[k]["value"] or 0) >= THRESHOLDS[k] for k in THRESHOLDS))
    return {"schema_version": 1, "experiment": "qwen-bounded-probe", "status": "pass" if passed else "fail",
            "model": {"id": MODEL_ID, "revision": MODEL_REVISION}, "seed": SEED, "prompt_manifest_sha256": prompt_manifest(SEED)["sha256"],
            "thresholds": THRESHOLDS, "metrics": metrics, "records": rows,
            "note": "First-turn tool calling only. No-match behavior and grounding are measured in the generation step."}


def blocked_report(missing: str) -> dict:
    return {"schema_version": 1, "experiment": "qwen-bounded-probe", "status": "blocked_not_run", "blocker": missing,
            "gpu_spend_usd": "0", "model": {"id": MODEL_ID, "revision": MODEL_REVISION},
            "prompt_manifest_sha256": prompt_manifest(SEED)["sha256"], "metrics": None, "records": []}


def write(report: dict, out: str) -> None:
    root = Path(out)
    root.parent.mkdir(parents=True, exist_ok=True)
    root.with_suffix(".json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    m = report["metrics"]
    lines = [f"# Qwen bounded probe: {report['status']}", ""]
    if m is None:
        lines += [f"Not run. {report['blocker']}", "GPU spend: $0."]
    else:
        lines += [f"Model `{MODEL_ID}@{MODEL_REVISION[:7]}`, 20 prompts, first turn.", "", "| Metric | Result |", "|---|---|"]
        lines += [f"| {k} | {v['numerator']}/{v['denominator']} |" for k, v in m.items() if isinstance(v, dict) and "numerator" in v]
        lines += [f"| retries | {m['retries']} |", f"| latency ms | {m['latency_ms']} |", f"| cost usd | {m['cost_usd']} |"]
    root.with_suffix(".md").write_text("\n".join(lines) + "\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env-file")
    ap.add_argument("--out", default="docs/spikes/results/qwen_probe")
    a = ap.parse_args(argv)
    if a.env_file:
        from scripts._env import load
        load(a.env_file, KEYS)
    from agents.qwen_client import ModalQwenClient
    try:
        client = ModalQwenClient.from_environment()
    except InferenceError as exc:
        write(blocked_report(str(exc)), a.out)
        print(json.dumps({"status": "blocked_not_run", "detail": str(exc)}))
        return 3
    report = run_probe(QwenModelAdapter(client, max_retries=1))
    write(report, a.out)
    print(json.dumps({"status": report["status"], "spent_estimate_usd": str(client.spent)}))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
