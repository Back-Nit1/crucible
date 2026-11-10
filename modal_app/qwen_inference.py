"""Modal inference server for the pinned Qwen checkpoint (the remote half of agents.qwen_client), optionally serving a
verified LoRA adapter produced by modal_app.qwen_training.

NOTHING here runs unless you deploy it. The GPU is attached only when CRUCIBLE_ENABLE_L4_PROBE=1 at deploy time, and
deploying is gated on: rotated Modal token confirmed, payment method on the workspace, and the user's approval of the
cost ceiling. See docs/handoffs/release-convergence.md and docs/handoffs/modal-training-runtime.md.

  CRUCIBLE_ENABLE_L4_PROBE=1 uv run modal deploy modal_app/qwen_inference.py     # user-approved only
  uv run modal app stop crucible-qwen-inference                                  # always stop afterwards

All request handling lives in modal_app.qwen_service (pure, tested offline); this file is only the Modal wiring.
Engine: vLLM (modal_app.qwen_service.VLLMEngine). Concurrent calls are gathered by `@modal.batched` into one GPU batch;
vLLM's prefix cache computes the shared system prompt + tool schemas once, and each request may use a different LoRA.
Model: CRUCIBLE_QWEN_MODEL (7b default, 1.5b for cheap world generations) is read at deploy time and baked into the
image, so the container serves exactly the pin the deploying client uses. Capacity: one L4 (24 GB); 7B bf16 is 15.2 GB,
1.5B is ~3 GB, the rest is KV cache. max_containers=1, no min_containers: the GPU scales to zero after
`scaledown_window` idle seconds and frees CUDA memory on exit."""
from __future__ import annotations

import os
import time
from pathlib import Path

import modal

from modal_app.qwen_toolcalls import MODEL_ID, MODEL_REVISION, QWEN_MODEL_KEY

APP_NAME = "crucible-qwen-inference"
FUNCTION_NAME = "Qwen.generate"
MODEL_PATH = f"/models/{MODEL_ID.rsplit('/', 1)[-1]}-{MODEL_REVISION[:7]}"
ENABLED = os.environ.get("CRUCIBLE_ENABLE_L4_PROBE") == "1"
REQUEST_TIMEOUT_SECONDS = 900  # a server-side input timeout also restarts the container, so keep it above any client wait
MAX_BATCH_SIZE, BATCH_WAIT_MS = 32, 50  # up to 32 agent calls per GPU step; wait at most 50 ms to fill a batch
ADAPTER_VOLUME = "crucible-qwen-adapters"  # written by modal_app.qwen_training; read-only here
ADAPTER_MOUNT = "/vol"
ADAPTER_RUNS_ROOT = f"{ADAPTER_MOUNT}/runs"


def _download_model() -> None:
    from huggingface_hub import snapshot_download
    snapshot_download(repo_id=MODEL_ID, revision=MODEL_REVISION, local_dir=MODEL_PATH,
                      ignore_patterns=["*.bin", "*.h5", "*.msgpack", "*.ot"])


image = (modal.Image.debian_slim(python_version="3.12")
         # vllm pins torch but only floors transformers; 5.x drops all_special_tokens_extended and crashes vllm startup
         .pip_install("vllm==0.32.0", "transformers==5.19.0", "pydantic==2.14.2", "jsonschema==4.23.0")
         # vllm 0.32 warms up a FlashInfer sampler that JIT-compiles with nvcc/ninja; this image has neither, so startup crashed
         .env({"CRUCIBLE_QWEN_MODEL": QWEN_MODEL_KEY, "VLLM_USE_FLASHINFER_SAMPLER": "0"})
         .add_local_python_source("modal_app", copy=True)
         .run_function(_download_model, timeout=30 * 60))
app = modal.App(APP_NAME)
adapters = modal.Volume.from_name(ADAPTER_VOLUME, create_if_missing=True, version=2)


@app.cls(image=image, gpu="L4" if ENABLED else None, cpu=2.0, memory=32_768, timeout=REQUEST_TIMEOUT_SECONDS,
         max_containers=1, scaledown_window=int(os.environ.get("CRUCIBLE_QWEN_SCALEDOWN_SECONDS", "60")),
         min_containers=int(os.environ.get("CRUCIBLE_QWEN_MIN_CONTAINERS", "0")), volumes={ADAPTER_MOUNT: adapters})
class Qwen:
    @modal.enter()
    def load(self) -> None:
        from modal_app.qwen_service import AdapterResolver, QwenService, VLLMEngine
        started = time.perf_counter()
        engine = VLLMEngine(MODEL_PATH)  # vLLM refuses to start without a GPU: no CPU fallback
        self.engine = engine
        self.service = QwenService(engine, AdapterResolver(Path(ADAPTER_RUNS_ROOT), reload=adapters.reload),
                                   container_load_seconds=time.perf_counter() - started)

    @modal.exit()
    def release(self) -> None:
        self.engine = self.service = None  # drop the vLLM engine so its GPU memory is released with the process

    @modal.batched(max_batch_size=MAX_BATCH_SIZE, wait_ms=BATCH_WAIT_MS)
    def generate(self, payloads: list[dict]) -> list[dict]:
        started = time.perf_counter()
        out = self.service.handle_batch(payloads)  # callers still send one payload and get one result back
        print(f"[batch] n={len(payloads)} seconds={time.perf_counter() - started:.2f}", flush=True)  # evidence for scale-down/replacement questions
        return out
