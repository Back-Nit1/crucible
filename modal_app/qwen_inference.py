"""Modal inference server for the pinned Qwen checkpoint (the remote half of agents.qwen_client), optionally serving a
verified LoRA adapter produced by modal_app.qwen_training.

NOTHING here runs unless you deploy it. The GPU is attached only when CRUCIBLE_ENABLE_L4_PROBE=1 at deploy time, and
deploying is gated on: rotated Modal token confirmed, payment method on the workspace, and the user's approval of the
cost ceiling. See docs/handoffs/release-convergence.md and docs/handoffs/modal-training-runtime.md.

  CRUCIBLE_ENABLE_L4_PROBE=1 uv run modal deploy modal_app/qwen_inference.py     # user-approved only
  uv run modal app stop crucible-qwen-inference                                  # always stop afterwards

All request handling lives in modal_app.qwen_service (pure, tested offline); this file is only the Modal wiring.
Capacity: one L4 (24 GB) holds the 15.2 GB bf16 weights, small LoRA adapters (<= MAX_LOADED_ADAPTERS) and the KV cache
for MAX_INPUT_TOKENS + MAX_NEW_TOKENS_CEILING tokens. max_containers=1 and one input at a time: adapter switching is
never concurrent. The container scales to zero after `scaledown_window` and frees CUDA memory on exit."""
from __future__ import annotations

import os
import time
from pathlib import Path

import modal

from modal_app.qwen_toolcalls import MODEL_ID, MODEL_REVISION

APP_NAME = "crucible-qwen-inference"
FUNCTION_NAME = "Qwen.generate"
MODEL_PATH = f"/models/{MODEL_ID.rsplit('/', 1)[-1]}-{MODEL_REVISION[:7]}"
ENABLED = os.environ.get("CRUCIBLE_ENABLE_L4_PROBE") == "1"
REQUEST_TIMEOUT_SECONDS = 300
ADAPTER_VOLUME = "crucible-qwen-adapters"  # written by modal_app.qwen_training; read-only here
ADAPTER_MOUNT = "/vol"
ADAPTER_RUNS_ROOT = f"{ADAPTER_MOUNT}/runs"


def _download_model() -> None:
    from huggingface_hub import snapshot_download
    snapshot_download(repo_id=MODEL_ID, revision=MODEL_REVISION, local_dir=MODEL_PATH,
                      ignore_patterns=["*.bin", "*.h5", "*.msgpack", "*.ot"])


image = (modal.Image.debian_slim(python_version="3.12")
         .pip_install("accelerate==1.4.0", "huggingface-hub==0.29.3", "pydantic==2.14.2", "jsonschema==4.23.0",
                      "peft==0.14.0", "safetensors==0.5.3", "torch==2.6.0", "transformers==4.49.0")
         .add_local_python_source("modal_app", copy=True)
         .run_function(_download_model, timeout=30 * 60))
app = modal.App(APP_NAME)
adapters = modal.Volume.from_name(ADAPTER_VOLUME, create_if_missing=True, version=2)


@app.cls(image=image, gpu="L4" if ENABLED else None, cpu=2.0, memory=32_768, timeout=REQUEST_TIMEOUT_SECONDS,
         max_containers=1, scaledown_window=60, volumes={ADAPTER_MOUNT: adapters})
class Qwen:
    @modal.enter()
    def load(self) -> None:
        from modal_app.qwen_service import AdapterResolver, QwenService, TransformersEngine
        started = time.perf_counter()
        engine = TransformersEngine(MODEL_PATH, device="cuda")  # raises without CUDA: no CPU deployment of a 7B model
        engine.torch.cuda.synchronize()
        self.engine = engine
        self.service = QwenService(engine, AdapterResolver(Path(ADAPTER_RUNS_ROOT), reload=adapters.reload),
                                   container_load_seconds=time.perf_counter() - started)

    @modal.exit()
    def release(self) -> None:
        engine = getattr(self, "engine", None)
        if engine is not None:
            engine.model = engine.peft = None
            engine.torch.cuda.empty_cache()

    @modal.method()
    def generate(self, payload: dict) -> dict:
        return self.service.handle(payload)
