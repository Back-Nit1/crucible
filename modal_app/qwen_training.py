"""Modal QLoRA/LoRA job (SFT or GRPO) for the pinned Qwen checkpoint.

NOTHING here runs unless you deploy AND call it. The GPU is attached only when CRUCIBLE_ENABLE_L4_TRAIN=1 (SFT) and/or
CRUCIBLE_ENABLE_L4_RL=1 (GRPO) at deploy time; the enabled algorithms are baked into the image and any other algorithm is
refused in the container (training.service.check_request). Without a flag the function has no GPU and fails closed.
Calling it is gated locally by training.gates.authorize_training (SFT and GRPO have separate approvals) and re-checked
inside the container.

  CRUCIBLE_ENABLE_L4_TRAIN=1 uv run modal deploy modal_app/qwen_training.py     # user-approved only
  CRUCIBLE_ENABLE_L4_RL=1 uv run modal deploy modal_app/qwen_training.py        # GRPO; user-approved only
  uv run python -m scripts.train_lora --launch ...                          # gated, bounded, resumable
  uv run modal app stop crucible-qwen-training                              # always stop afterwards

The file is named qwen_training (not training) on purpose: `modal deploy` may import it as a top-level module, which would
shadow the `training` package inside the container.

State lives on the `crucible-qwen-adapters` Volume: runs/<run_id>/{identity.json,ledger.json,dataset.jsonl,
checkpoints/,final/}. `final/` (adapter + artifact_manifest.json) is what modal_app.qwen_inference serves."""
from __future__ import annotations

import os
from pathlib import Path

import modal

from modal_app.qwen_toolcalls import MODEL_ID, MODEL_REVISION
from modal_app.train_protocol import TrainRequest, TrainResponse

APP_NAME = "crucible-qwen-training"
FUNCTION_NAME = "train"
VOLUME_NAME = "crucible-qwen-adapters"
VOLUME_ROOT = "/vol"
RUNS_ROOT = f"{VOLUME_ROOT}/runs"
MODEL_PATH = f"/models/{MODEL_ID.rsplit('/', 1)[-1]}-{MODEL_REVISION[:7]}"
ALGORITHMS = ",".join(name for name, var in (("sft", "CRUCIBLE_ENABLE_L4_TRAIN"), ("grpo", "CRUCIBLE_ENABLE_L4_RL"))
                      if os.environ.get(var) == "1")
ENABLED = bool(ALGORITHMS)
TIMEOUT_SECONDS = 45 * 60  # hard backstop; the loop soft-stops at training.gates.MAX_LAUNCH_SECONDS (43 min)
# Pins shared with modal_app.qwen_inference where they overlap; peft/bitsandbytes are the training additions.
# peft 0.14.0 and bitsandbytes 0.45.3 predate transformers 4.49.0 / torch 2.6.0 and list no upper bounds on either.
TRAIN_PINS = ("accelerate==1.4.0", "bitsandbytes==0.45.3", "huggingface-hub==0.29.3", "jsonschema==4.23.0", "peft==0.14.0",
              "pydantic==2.14.2", "safetensors==0.5.3", "torch==2.6.0", "transformers==4.49.0")


def _download_model() -> None:
    from huggingface_hub import snapshot_download
    snapshot_download(repo_id=MODEL_ID, revision=MODEL_REVISION, local_dir=MODEL_PATH,
                      ignore_patterns=["*.bin", "*.h5", "*.msgpack", "*.ot"])


image = (modal.Image.debian_slim(python_version="3.12")
         .pip_install(*TRAIN_PINS)
         .add_local_python_source("modal_app", "training", copy=True)
         .run_function(_download_model, timeout=30 * 60)
         .env({"CRUCIBLE_TRAIN_ALGORITHMS": ALGORITHMS}))  # last layer: flipping a flag never re-downloads the model
app = modal.App(APP_NAME)
volume = modal.Volume.from_name(VOLUME_NAME, create_if_missing=True, version=2)


@app.function(image=image, gpu="L4" if ENABLED else None, cpu=2.0, memory=32_768, timeout=TIMEOUT_SECONDS,
              volumes={VOLUME_ROOT: volume}, max_containers=1, retries=0)
def train(payload: dict) -> dict:
    """One launch of a (possibly resumed) run. Returns a TrainResponse; status "final" only with a verified artifact."""
    from training.service import execute, policy_adapter_dir
    from training.torch_backend import TorchLoraBackend, backend_signature, load_base_model
    request = TrainRequest.model_validate(payload)
    volume.reload()
    hp = request.plan.hyperparameters
    model, tokenizer = load_base_model(MODEL_PATH, hp, device="cuda")  # raises (no CPU fallback) without CUDA

    def backend_factory(shard, hyperparameters, total_steps):
        return TorchLoraBackend(model=model, tokenizer=tokenizer, shard=shard, hp=hyperparameters, total_steps=total_steps,
                                device="cuda", policy_adapter_dir=policy_adapter_dir(Path(RUNS_ROOT), request.plan))

    Path(RUNS_ROOT).mkdir(parents=True, exist_ok=True)
    response: TrainResponse = execute(request, runs_root=Path(RUNS_ROOT), backend_factory=backend_factory,
                                      signature=backend_signature(), volume_commit=volume.commit,
                                      algorithms=frozenset(filter(None, os.environ.get("CRUCIBLE_TRAIN_ALGORITHMS", "").split(","))))
    return response.model_dump(mode="json")
