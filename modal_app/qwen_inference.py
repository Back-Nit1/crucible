"""Modal inference server for the pinned Qwen checkpoint (the remote half of agents.qwen_client).

NOTHING here runs unless you deploy it. The GPU is attached only when CRUCIBLE_ENABLE_L4_PROBE=1 at deploy time, and
deploying is gated on: rotated Modal token confirmed, payment method on the workspace, and the user's approval of the
cost ceiling. See docs/handoffs/release-convergence.md.

  CRUCIBLE_ENABLE_L4_PROBE=1 uv run modal deploy modal_app/qwen_inference.py     # user-approved only
  uv run modal app stop crucible-qwen-inference                                  # always stop afterwards
"""
from __future__ import annotations

import os
import time

import modal

from modal_app.qwen_protocol import QwenRequest, QwenResult
from modal_app.qwen_toolcalls import MODEL_ID, MODEL_REVISION

APP_NAME = "crucible-qwen-inference"
FUNCTION_NAME = "Qwen.generate"
MODEL_PATH = f"/models/{MODEL_ID.rsplit('/', 1)[-1]}-{MODEL_REVISION[:7]}"
ENABLED = os.environ.get("CRUCIBLE_ENABLE_L4_PROBE") == "1"
REQUEST_TIMEOUT_SECONDS = 300


def _download_model() -> None:
    from huggingface_hub import snapshot_download
    snapshot_download(repo_id=MODEL_ID, revision=MODEL_REVISION, local_dir=MODEL_PATH,
                      ignore_patterns=["*.bin", "*.h5", "*.msgpack", "*.ot"])


image = (modal.Image.debian_slim(python_version="3.12")
         .pip_install("accelerate==1.4.0", "huggingface-hub==0.29.3", "pydantic==2.14.2", "jsonschema==4.23.0",
                      "safetensors==0.5.3", "torch==2.6.0", "transformers==4.49.0")
         .add_local_python_source("modal_app", copy=True)
         .run_function(_download_model, timeout=30 * 60))
app = modal.App(APP_NAME)


@app.cls(image=image, gpu="L4" if ENABLED else None, cpu=2.0, memory=32_768, timeout=REQUEST_TIMEOUT_SECONDS,
         max_containers=1, scaledown_window=60)
class Qwen:
    @modal.enter()
    def load(self) -> None:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        if not torch.cuda.is_available():
            raise RuntimeError("no CUDA device: refusing to serve a 7B model on CPU")
        started = time.perf_counter()
        self.tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH, local_files_only=True)
        self.model = AutoModelForCausalLM.from_pretrained(MODEL_PATH, torch_dtype=torch.bfloat16, device_map="cuda",
                                                          local_files_only=True, low_cpu_mem_usage=True).eval()
        torch.cuda.synchronize()
        self.load_seconds, self.reported_load = time.perf_counter() - started, False

    @modal.method()
    def generate(self, payload: dict) -> dict:
        import torch
        request = QwenRequest.model_validate(payload)  # strict: unknown fields, oversize or wrong revision are rejected
        if (request.model, request.revision) != (MODEL_ID, MODEL_REVISION):
            raise ValueError("requested model/revision is not the pinned checkpoint")
        messages = [{"role": "system", "content": request.system}, *request.messages]
        rendered = self.tokenizer.apply_chat_template(messages, tools=request.tools, add_generation_prompt=True,
                                                      tokenize=False)
        inputs = self.tokenizer(rendered, return_tensors="pt").to("cuda")
        sampling = request.temperature > 0
        if sampling:
            torch.manual_seed(request.seed)
        torch.cuda.synchronize()
        started = time.perf_counter()
        with torch.inference_mode():
            out = self.model.generate(**inputs, do_sample=sampling, max_new_tokens=request.max_new_tokens,
                                      pad_token_id=self.tokenizer.eos_token_id,
                                      **({"temperature": request.temperature} if sampling else {}))
        torch.cuda.synchronize()
        generated = out[0, inputs["input_ids"].shape[1]:]
        load = 0.0 if self.reported_load else self.load_seconds
        self.reported_load = True
        return QwenResult(
            raw_output=self.tokenizer.decode(generated, skip_special_tokens=False),
            input_tokens=int(inputs["input_ids"].shape[1]), output_tokens=int(generated.shape[0]),
            finish_reason="stop" if int(generated[-1]) in {self.tokenizer.eos_token_id, self.tokenizer.convert_tokens_to_ids("<|im_end|>")}
            else "length", model=MODEL_ID, revision=MODEL_REVISION, seed_applied=True,  # greedy needs none; sampling is seeded
            generation_seconds=time.perf_counter() - started, container_load_seconds=load).model_dump(mode="json")
