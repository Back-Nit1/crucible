"""Bounded Modal probes for Qwen tool calling and Volume resumability.

Commands:

    modal run modal_app/day1_probe.py::tool_call_probe
    modal run modal_app/day1_probe.py::checkpoint_resume_probe

The GPU function has a 45-minute hard timeout.  At current list prices the
requested L4 + CPU + RAM ceiling is below $1, safely under the $5 experiment
budget.  No training is performed here.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

import modal

from modal_app.qwen_toolcalls import (
    MODEL_ID,
    MODEL_REVISION,
    SEED,
    SYSTEM_PROMPT,
    TOOL_SCHEMAS,
    estimate_modal_cost,
    prompt_manifest,
    representative_prompts,
    summarize_records,
)

APP_NAME = "crucible-day1-modal-qwen"
MODEL_PATH = f"/models/{MODEL_ID.rsplit('/', 1)[-1]}-{MODEL_REVISION[:7]}"
CHECKPOINT_ROOT = Path("/checkpoints/day1-resume")
MAX_GPU_SECONDS = 45 * 60
MAX_EXPERIMENT_SPEND_USD = 5.0
DEFAULT_TOOL_RESULT = "docs/spikes/results/day1_qwen_tool_calls.json"
DEFAULT_RESUME_RESULT = "docs/spikes/results/day1_modal_resume.json"
L4_PROBE_ENABLED = os.environ.get("CRUCIBLE_ENABLE_L4_PROBE") == "1"


def _download_model() -> None:
    """Bake only the pinned safetensors checkpoint into the immutable image."""

    from huggingface_hub import snapshot_download

    snapshot_download(
        repo_id=MODEL_ID,
        revision=MODEL_REVISION,
        local_dir=MODEL_PATH,
        ignore_patterns=["*.bin", "*.h5", "*.msgpack", "*.ot"],
    )


model_image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "accelerate==1.4.0",
        "huggingface-hub==0.29.3",
        "jsonschema==4.23.0",
        "safetensors==0.5.3",
        "torch==2.6.0",
        "transformers==4.49.0",
    )
    .add_local_python_source("modal_app", copy=True)
    .run_function(_download_model, timeout=30 * 60)
)

cpu_image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("jsonschema==4.23.0")
    .add_local_python_source("modal_app", copy=True)
)
checkpoint_volume = modal.Volume.from_name(
    "crucible-day1-checkpoints-v2", create_if_missing=True, version=2
)
app = modal.App(APP_NAME)


def _sanitize(value: str) -> str:
    """Defensively remove credential-shaped strings from persisted output."""

    value = re.sub(r"\b(?:ak|as)-[A-Za-z0-9_-]{8,}\b", "[REDACTED_MODAL_TOKEN]", value)
    return re.sub(r"\bhf_[A-Za-z0-9]{8,}\b", "[REDACTED_HF_TOKEN]", value)


@app.function(
    image=model_image,
    # Keep CPU-only diagnostics runnable in workspaces without GPU billing.
    # The local GPU entrypoint below refuses to run unless this is explicitly enabled.
    gpu="L4" if L4_PROBE_ENABLED else None,
    cpu=2.0,
    memory=32_768,
    timeout=MAX_GPU_SECONDS,
    max_containers=1,
    single_use_containers=True,
)
def run_tool_call_probe(submitted_at: float) -> dict[str, Any]:
    """Run exactly one deterministic first-turn generation for each prompt."""

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    container_started_at = time.time()
    dispatch_to_container_seconds = container_started_at - submitted_at
    cuda_available = torch.cuda.is_available()
    if not cuda_available:
        raise RuntimeError("Modal allocated the probe without a CUDA device")

    gpu_name = torch.cuda.get_device_name(0)
    gpu_memory_gib = torch.cuda.get_device_properties(0).total_memory / (1024**3)
    load_started = time.perf_counter()
    tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH, local_files_only=True)
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_PATH,
        torch_dtype=torch.bfloat16,
        device_map="cuda",
        local_files_only=True,
        low_cpu_mem_usage=True,
    )
    model.eval()
    torch.cuda.synchronize()
    model_load_seconds = time.perf_counter() - load_started

    torch.manual_seed(SEED)
    records: list[dict[str, Any]] = []
    for prompt in representative_prompts(SEED):
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt.text},
        ]
        rendered = tokenizer.apply_chat_template(
            messages,
            tools=TOOL_SCHEMAS,
            add_generation_prompt=True,
            tokenize=False,
        )
        inputs = tokenizer(rendered, return_tensors="pt").to("cuda")
        torch.cuda.synchronize()
        started = time.perf_counter()
        with torch.inference_mode():
            generated = model.generate(
                **inputs,
                do_sample=False,
                max_new_tokens=192,
                pad_token_id=tokenizer.eos_token_id,
            )
        torch.cuda.synchronize()
        latency = time.perf_counter() - started
        generated_tokens = generated[0, inputs["input_ids"].shape[1] :]
        raw_output = tokenizer.decode(generated_tokens, skip_special_tokens=False)
        records.append(
            {
                "task_id": prompt.task_id,
                "expected_feasibility": prompt.expected_feasibility,
                "traits": list(prompt.traits),
                "prompt": prompt.text,
                "raw_output": _sanitize(raw_output),
                "input_tokens": int(inputs["input_ids"].shape[1]),
                "output_tokens": int(generated_tokens.shape[0]),
                "latency_seconds": round(latency, 6),
            }
        )

    function_runtime_seconds = time.time() - container_started_at
    result = {
        "schema_version": 1,
        "experiment": "qwen-day1-structured-tool-calling",
        "seed": SEED,
        "model": {"id": MODEL_ID, "revision": MODEL_REVISION, "dtype": "bfloat16"},
        "modal": {
            "requested_gpu": "L4",
            "actual_gpu": gpu_name,
            "gpu_available": cuda_available,
            "gpu_memory_gib": round(gpu_memory_gib, 3),
            "dispatch_to_container_seconds": round(dispatch_to_container_seconds, 6),
            "model_load_seconds": round(model_load_seconds, 6),
            "function_runtime_seconds": round(function_runtime_seconds, 6),
            "hard_timeout_seconds": MAX_GPU_SECONDS,
        },
        "prompt_manifest": prompt_manifest(SEED),
        "records": records,
    }
    result["metrics"] = summarize_records(records, function_runtime_seconds)
    return result


def _state_path(run_id: str) -> Path:
    if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,80}", run_id):
        raise ValueError("run_id must contain only letters, digits, dot, underscore, or dash")
    return CHECKPOINT_ROOT / run_id / "latest.json"


@app.function(
    image=cpu_image,
    volumes={CHECKPOINT_ROOT.parent: checkpoint_volume},
    cpu=0.125,
    memory=256,
    timeout=5 * 60,
    retries=0,
)
def checkpoint_steps(run_id: str, target_steps: int, stop_after_step: int | None) -> dict[str, Any]:
    """Commit each step, optionally terminate after a checkpoint, then resume later."""

    checkpoint_volume.reload()
    path = _state_path(run_id)
    if path.exists():
        state = json.loads(path.read_text())
    else:
        state = {"run_id": run_id, "step": 0, "history": []}
    resumed_from_step = int(state["step"])
    for step in range(resumed_from_step + 1, target_steps + 1):
        state["step"] = step
        state["history"].append({"step": step, "value": step * step})
        state["saved_at_epoch"] = time.time()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, sort_keys=True))
        os.replace(temporary, path)
        checkpoint_volume.commit()
        if stop_after_step is not None and step == stop_after_step:
            raise RuntimeError(f"intentional stop after committed step {step}")
    return {
        "run_id": run_id,
        "resumed_from_step": resumed_from_step,
        "completed_step": state["step"],
        "history": state["history"],
    }


@app.function(
    image=cpu_image,
    volumes={CHECKPOINT_ROOT.parent: checkpoint_volume},
    cpu=0.125,
    memory=256,
    timeout=60,
)
def inspect_checkpoint(run_id: str) -> dict[str, Any]:
    checkpoint_volume.reload()
    return json.loads(_state_path(run_id).read_text())


def _write_result(path: str, result: dict[str, Any]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


@app.local_entrypoint()
def tool_call_probe(output_path: str = DEFAULT_TOOL_RESULT) -> None:
    if not L4_PROBE_ENABLED:
        raise RuntimeError(
            "set CRUCIBLE_ENABLE_L4_PROBE=1 after authentication, billing, and cost checks"
        )
    ceiling = estimate_modal_cost(MAX_GPU_SECONDS)["total_usd"]
    if ceiling >= MAX_EXPERIMENT_SPEND_USD:
        raise RuntimeError(
            f"estimated GPU probe ceiling ${ceiling:.2f} exceeds ${MAX_EXPERIMENT_SPEND_USD:.2f}"
        )
    result = run_tool_call_probe.remote(submitted_at=time.time())
    _write_result(output_path, result)
    print(
        json.dumps(
            {
                "result_path": output_path,
                "task_count": result["metrics"]["task_count"],
                "estimated_cost_usd": result["metrics"]["estimated_modal_cost"]["total_usd"],
            },
            sort_keys=True,
        )
    )


@app.local_entrypoint()
def checkpoint_resume_probe(output_path: str = DEFAULT_RESUME_RESULT, run_id: str = "") -> None:
    selected_run_id = run_id or f"day1-{int(time.time())}"
    started = time.perf_counter()
    stopped_error_type = None
    try:
        checkpoint_steps.remote(
            run_id=selected_run_id, target_steps=6, stop_after_step=3
        )
    except Exception as error:  # Modal surfaces the intentional remote termination locally.
        stopped_error_type = type(error).__name__
    state_after_stop = inspect_checkpoint.remote(selected_run_id)
    resumed = checkpoint_steps.remote(
        run_id=selected_run_id, target_steps=6, stop_after_step=None
    )
    final_state = inspect_checkpoint.remote(selected_run_id)
    result = {
        "schema_version": 1,
        "experiment": "modal-volume-checkpoint-resume",
        "run_id": selected_run_id,
        "intentional_stop_observed": stopped_error_type is not None,
        "stopped_error_type": stopped_error_type,
        "state_after_stop": state_after_stop,
        "resume_result": resumed,
        "final_state": final_state,
        "wall_seconds": round(time.perf_counter() - started, 6),
        "success": (
            stopped_error_type is not None
            and state_after_stop["step"] == 3
            and resumed["resumed_from_step"] == 3
            and final_state["step"] == 6
            and [entry["step"] for entry in final_state["history"]] == list(range(1, 7))
        ),
    }
    _write_result(output_path, result)
    print(json.dumps({"result_path": output_path, "success": result["success"]}, sort_keys=True))
