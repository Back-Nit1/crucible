"""Bounded Qwen tool-calling probe: exactly the 20 seeded prompts, one first turn each, through the production
adapter/client stack (ModalQwenClient -> QwenModelAdapter). Refuses to start without launch authorization.

  uv run python -m scripts.qwen_probe --env-file <.env> [--out docs/spikes/results/qwen_probe]
  uv run python -m scripts.qwen_probe --adapter-manifest <.../final/artifact_manifest.json> --out docs/model-runs/<run>/probe_adapter

Requires the user to have: rotated the Modal token, added a payment method, deployed modal_app/qwen_inference.py with
CRUCIBLE_ENABLE_L4_PROBE=1, and exported CRUCIBLE_MODAL_TOKEN_ROTATED=1, CRUCIBLE_MODAL_BILLING_CONFIRMED=1 and
CRUCIBLE_MODAL_APPROVED_CEILING_USD=<approved>. Artifacts hold hashes, counts and codes only: never raw model output.

The PASS BAR is recorded in the artifact separately from the RESULT. It is a proposal (no numeric bar existed before):
  valid structured call >= 90% of 20 prompts, schema-valid arguments >= 90% of the structured calls, parse_intent first >= 90%
  of 20 prompts. Anything below is `failed`; `passed` is only ever written for a run that really executed against Modal.
Final status is one of: blocked_not_run, failed, passed."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import statistics
import sys
from collections.abc import Callable, Mapping
from decimal import Decimal
from pathlib import Path

from agents.model import (InferenceError, MalformedModelOutput, Message, ModelAdapter, ModelRequest, QwenModelAdapter,
                          action_tools)
from agents.qwen_client import BILLED_SPEND_VAR, LAUNCH_FLAGS, CEILING_VAR, qwen_tools
from modal_app.qwen_toolcalls import MODEL_ID, MODEL_REVISION, SEED, SYSTEM_PROMPT, prompt_manifest, representative_prompts

SCHEMA_VERSION = 2
PROMPT_COUNT = 20
THRESHOLDS = {"valid_structured_call": 0.90, "schema_valid_arguments": 0.90, "parse_intent_first": 0.90}
PASS_BAR = {"version": "proposed-2026-11-01", "prompt_count": PROMPT_COUNT, "thresholds": THRESHOLDS, "status": "proposed",
            "note": "proposed by the implementer; not yet confirmed by the product owner; the probe is first-turn only"}
METRIC_DEFINITIONS = {
    "valid_structured_call": "cases (of 20) whose final output held exactly one closed tool call naming an offered tool "
                             "with an argument object (schema-valid or not)",
    "schema_valid_arguments": "of those structured calls, how many passed the typed action schema",
    "parse_intent_first": "cases (of 20) whose first tool call is parse_intent with schema-valid arguments",
}
KEYS = {*LAUNCH_FLAGS, CEILING_VAR, BILLED_SPEND_VAR}


def _rate(n: int, d: int) -> dict:
    return {"numerator": n, "denominator": d, "value": None if not d else round(n / d, 4)}


def _pct(values: list[float], q: float) -> float | None:
    return sorted(values)[min(len(values) - 1, int(q * len(values)))] if values else None


def tool_schema_sha256() -> str:
    return hashlib.sha256(json.dumps(qwen_tools(action_tools()), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def authorization_state(env: Mapping[str, str] | None = None) -> dict:
    env = os.environ if env is None else env
    return {"token_rotated_confirmed": env.get(LAUNCH_FLAGS[0]) == "1", "billing_confirmed": env.get(LAUNCH_FLAGS[1]) == "1",
            "approved_ceiling_usd": env.get(CEILING_VAR) or None}


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _model_block(checkpoint: str, adapter_hash: str | None, training_manifest_hash: str | None) -> dict:
    return {"id": MODEL_ID, "revision": MODEL_REVISION, "checkpoint": checkpoint, "adapter_hash": adapter_hash,
            "training_manifest_hash": training_manifest_hash}


def run_probe(adapter: ModelAdapter, *, temperature: str = "0", checkpoint: str = "qwen-base", adapter_hash: str | None = None,
              training_manifest_hash: str | None = None, spent: Callable[[], Decimal] | None = None,
              ceiling: Decimal | None = None, authorization: dict | None = None, clock: Callable[[], dt.datetime] = _now) -> dict:
    prompts = representative_prompts(SEED)
    if len(prompts) != PROMPT_COUNT:
        raise RuntimeError(f"the bounded probe is exactly {PROMPT_COUNT} prompts, found {len(prompts)}")
    started = clock()
    rows = []
    for i, prompt in enumerate(prompts):
        request = ModelRequest(
            request_id=f"probe:{prompt.task_id}", sequence=0, system_prompt=SYSTEM_PROMPT, seed=SEED + i,
            messages=(Message(role="user", content=prompt.text),), tools=action_tools(),
            temperature=Decimal(temperature), checkpoint=checkpoint)
        row = {"task_id": prompt.task_id, "expected_feasibility": prompt.expected_feasibility, "traits": list(prompt.traits)}
        try:
            out = adapter.generate(request)
            call = out.tool_calls[0]
            row |= {"outcome": "valid", "structured_call": True, "schema_valid": True, "tool": call.name,
                    "parse_intent_first": call.name == "parse_intent",
                    "prompt_tokens": out.prompt_tokens, "completion_tokens": out.completion_tokens, "latency_ms": out.latency_ms,
                    "retry_count": out.retry_count, "finish_reason": out.finish_reason, "cost": str(out.cost),
                    "cost_known": out.cost_known, "raw_output_hash": out.raw_output_hash}
        except MalformedModelOutput as exc:
            errors = [a.get("error") for a in exc.attempts]
            # A pydantic ValidationError means the envelope parsed and named an offered tool but its arguments failed the
            # typed schema; anything else (no closed block, bad JSON, tool not offered) is not a structured call.
            row |= {"outcome": "malformed", "structured_call": errors[-1] == "ValidationError", "schema_valid": False,
                    "parse_intent_first": False, "attempts": len(exc.attempts), "retry_count": len(exc.attempts) - 1,
                    "raw_output_hashes": [a.get("raw_output_hash") for a in exc.attempts], "error_types": errors}
        except InferenceError as exc:
            row |= {"outcome": "inference_error", "structured_call": False, "schema_valid": False, "parse_intent_first": False,
                    "error_code": exc.code, "retryable": exc.retryable}
        rows.append(row)
    finished = clock()
    valid = [r for r in rows if r["outcome"] == "valid"]
    structured = [r for r in rows if r["structured_call"]]
    lat = [float(r["latency_ms"]) for r in valid]
    total_cost = spent() if spent else None
    metrics = {
        "valid_structured_call": _rate(len(structured), len(rows)),
        "schema_valid_arguments": _rate(len(valid), len(structured)),
        "parse_intent_first": _rate(sum(r["parse_intent_first"] for r in rows), len(rows)),
        "first_attempt_valid": _rate(sum(r["outcome"] == "valid" and r["retry_count"] == 0 for r in rows), len(rows)),
        "malformed": _rate(sum(r["outcome"] == "malformed" for r in rows), len(rows)),
        "inference_errors": _rate(sum(r["outcome"] == "inference_error" for r in rows), len(rows)),
        "retries": sum(r.get("retry_count", 0) for r in rows),
        "tokens": {"prompt": sum(r.get("prompt_tokens", 0) for r in valid), "completion": sum(r.get("completion_tokens", 0) for r in valid),
                   "measured_over": len(valid)},
        "latency_ms": {"mean": round(statistics.fmean(lat), 1) if lat else None, "p50": _pct(lat, .5), "p95": _pct(lat, .95),
                       "max": max(lat) if lat else None, "measured_over": len(lat)},
        # Total spend comes from the client's own meter (includes retries and malformed attempts). Without a meter the
        # cost is UNKNOWN, never zero.
        "cost_usd": {"total": None if total_cost is None else str(total_cost),
                     "per_prompt": None if total_cost is None else str(total_cost / len(rows)),
                     "known": total_cost is not None and all(r.get("cost_known", True) for r in valid),
                     "ceiling": None if ceiling is None else str(ceiling),
                     "ceiling_exceeded": None if total_cost is None or ceiling is None else total_cost > ceiling,
                     "basis": "measured generation seconds x Modal list rates (estimate; Modal billing is the truth)"},
    }
    failed = [k for k in THRESHOLDS if (metrics[k]["value"] or 0) < THRESHOLDS[k]]
    status = "passed" if rows and not failed else "failed"
    return {"schema_version": SCHEMA_VERSION, "experiment": "qwen-bounded-probe", "status": status,
            "pass_bar": PASS_BAR, "result": {"status": status, "failed_thresholds": failed},
            "metric_definitions": METRIC_DEFINITIONS, "model": _model_block(checkpoint, adapter_hash, training_manifest_hash),
            "seed": SEED, "prompt_manifest_sha256": prompt_manifest(SEED)["sha256"], "tool_schema_sha256": tool_schema_sha256(),
            "authorization": authorization or authorization_state(), "started_at": started.isoformat(),
            "finished_at": finished.isoformat(), "metrics": metrics, "records": rows,
            "note": "First-turn tool calling only. No-match behavior and grounding are measured in the generation step."}


def blocked_report(missing: str, *, authorization: dict | None = None, checkpoint: str = "qwen-base",
                   adapter_hash: str | None = None, training_manifest_hash: str | None = None,
                   clock: Callable[[], dt.datetime] = _now) -> dict:
    return {"schema_version": SCHEMA_VERSION, "experiment": "qwen-bounded-probe", "status": "blocked_not_run", "blocker": missing,
            "pass_bar": PASS_BAR, "result": {"status": "blocked_not_run", "failed_thresholds": []}, "gpu_spend_usd": "0",
            "model": _model_block(checkpoint, adapter_hash, training_manifest_hash), "seed": SEED,
            "prompt_manifest_sha256": prompt_manifest(SEED)["sha256"], "tool_schema_sha256": tool_schema_sha256(),
            "authorization": authorization or authorization_state(), "started_at": None, "finished_at": clock().isoformat(),
            "metrics": None, "records": []}


def write(report: dict, out: str) -> None:
    root = Path(out)
    root.parent.mkdir(parents=True, exist_ok=True)
    root.with_suffix(".json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    m = report["metrics"]
    lines = [f"# Qwen bounded probe: {report['status']}", ""]
    if m is None:
        lines += [f"Not run. {report['blocker']}", "GPU spend: $0."]
    else:
        model = report["model"]
        lines += [f"Model `{model['id']}@{model['revision'][:7]}` checkpoint `{model['checkpoint']}`, {PROMPT_COUNT} prompts, first turn.",
                  "", "| Metric | Result |", "|---|---|"]
        lines += [f"| {k} | {v['numerator']}/{v['denominator']} |" for k, v in m.items() if isinstance(v, dict) and "numerator" in v]
        lines += [f"| retries | {m['retries']} |", f"| tokens | {m['tokens']} |", f"| latency ms | {m['latency_ms']} |",
                  f"| cost usd | {m['cost_usd']} |", "", f"Pass bar ({PASS_BAR['status']}): {PASS_BAR['thresholds']}"]
    root.with_suffix(".md").write_text("\n".join(lines) + "\n")


def main(argv=None, *, client_factory=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env-file")
    ap.add_argument("--out", default="docs/spikes/results/qwen_probe")
    ap.add_argument("--adapter-manifest", help="probe this trained adapter (artifact_manifest.json) instead of the base model")
    a = ap.parse_args(argv)
    if a.env_file:
        from scripts._env import load
        load(a.env_file, KEYS)
    selection, checkpoint, adapter_hash, tm_hash = None, "qwen-base", None, None
    if a.adapter_manifest:
        from modal_app.adapter_artifact import load_manifest
        manifest = load_manifest(Path(a.adapter_manifest))
        selection, checkpoint, adapter_hash, tm_hash = manifest.selection, manifest.checkpoint_id, manifest.adapter_hash, manifest.training_manifest_hash
    from agents.qwen_client import ModalQwenClient
    try:
        make = client_factory or ModalQwenClient.from_environment
        client = make(adapter=selection) if selection else make()
        if client_factory is None:
            from agents.qwen_client import warm_up_modal
            warm_up_modal()
    except InferenceError as exc:
        write(blocked_report(str(exc), checkpoint=checkpoint, adapter_hash=adapter_hash, training_manifest_hash=tm_hash), a.out)
        print(json.dumps({"status": "blocked_not_run", "detail": str(exc)}))
        return 3
    report = run_probe(QwenModelAdapter(client, max_retries=1), checkpoint=checkpoint, adapter_hash=adapter_hash,
                       training_manifest_hash=tm_hash, spent=lambda: client.budget.total_spent,
                       ceiling=client.cost_ceiling)
    write(report, a.out)
    print(json.dumps({"status": report["status"], "session_spent_estimate_usd": str(client.spent),
                      "cumulative_spent_estimate_usd": str(client.budget.total_spent)}))
    return {"passed": 0, "failed": 1}[report["status"]]


if __name__ == "__main__":
    sys.exit(main())
