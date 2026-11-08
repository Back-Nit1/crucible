"""Server-side request handling for the Qwen inference function, with the model numerics behind an `Engine` seam.

This module is the whole policy of the inference server and contains no `modal` import: pinned-model check, strict
request validation, adapter resolution + verification (BEFORE inference), input bounds, and response identity. The
real engine (`TransformersEngine`) lives at the bottom and imports torch lazily; tests drive the same service with a
fake engine and, separately, drive the real engine on a tiny model.

Adapter rule: if a request names an adapter, the response is that adapter's output or a QwenRejection. There is no
path that answers an adapter request from the base model."""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pydantic import ValidationError

from modal_app.adapter_artifact import (MANIFEST_FILENAME, AdapterSelection, ArtifactError, ArtifactManifest, load_manifest,
                                        verify_adapter_dir, verify_selection)
from modal_app.qwen_protocol import MAX_INPUT_TOKENS, MAX_NEW_TOKENS_CEILING, QwenRejection, QwenRequest, QwenResult
from modal_app.qwen_toolcalls import MODEL_ID, MODEL_REVISION

MAX_LOADED_ADAPTERS = 4


class InputTooLong(ValueError):
    pass


@dataclass(frozen=True)
class EngineOutput:
    raw_output: str
    input_tokens: int
    output_tokens: int
    finish_reason: str
    generation_seconds: float


class Engine(Protocol):
    def load_adapter(self, name: str, directory: Path) -> None: ...
    def unload_adapter(self, name: str) -> None: ...
    def generate(self, request: QwenRequest, adapter: str | None) -> EngineOutput:
        """adapter=None MUST run the pure base model, even if adapters are loaded. Raises InputTooLong."""


class AdapterResolver:
    """Maps a selection to a verified on-disk adapter. `root/<run_id>/final/` is the only place it ever looks; the
    selection carries identity only, so a request cannot name a path."""

    def __init__(self, root: Path, reload: Callable[[], None] = lambda: None):
        self.root, self.reload = root, reload
        self._verified: dict[str, Path] = {}  # adapter_hash -> directory whose bytes were hashed in this process

    def resolve(self, selection: AdapterSelection) -> tuple[ArtifactManifest, Path]:
        self.reload()
        directory = self.root / selection.run_id / "final"
        manifest_path = directory / MANIFEST_FILENAME
        if not manifest_path.is_file():
            raise ArtifactError("adapter_missing", "no final artifact for that run")
        manifest = load_manifest(manifest_path)
        verify_selection(manifest, selection, base_model=MODEL_ID, base_revision=MODEL_REVISION)
        if self._verified.get(manifest.adapter_hash) != directory:
            verify_adapter_dir(manifest, directory)  # hashes every file: tamper / truncation / extra files fail here
            self._verified[manifest.adapter_hash] = directory
        return manifest, directory


class QwenService:
    def __init__(self, engine: Engine, resolver: AdapterResolver, *, container_load_seconds: float = 0.0,
                 monotonic: Callable[[], float] = time.perf_counter):
        self.engine, self.resolver, self.monotonic = engine, resolver, monotonic
        self.container_load_seconds, self._load_reported = container_load_seconds, False
        self.loaded: list[str] = []  # adapter names, oldest first

    def _ensure_adapter(self, manifest: ArtifactManifest, directory: Path) -> float:
        name = manifest.checkpoint_id
        if name in self.loaded:
            return 0.0
        if len(self.loaded) >= MAX_LOADED_ADAPTERS:
            self.engine.unload_adapter(self.loaded.pop(0))
        started = self.monotonic()
        self.engine.load_adapter(name, directory)
        self.loaded.append(name)
        return self.monotonic() - started

    def handle(self, payload: dict) -> dict:
        return self.handle_batch([payload])[0]

    def handle_batch(self, payloads: list[dict]) -> list[dict]:
        """Validate and resolve each request on its own (one bad request never fails the others), then ONE engine call
        for the rest. A batching engine (vLLM) runs them together and reuses their shared prompt prefix; otherwise
        requests run one at a time. Results come back in request order."""
        out: list[dict] = [{}] * len(payloads)
        todo = []  # (index, request, manifest, adapter_seconds, adapter name)
        for i, payload in enumerate(payloads):
            prepared = self._prepare(payload)
            if isinstance(prepared, dict):
                out[i] = prepared
            else:
                todo.append((i, *prepared))
        work = [(request, name) for _, request, _, _, name in todo]
        batch = getattr(self.engine, "generate_batch", None)
        results = batch(work) if batch else [self._generate_one(request, name) for request, name in work]
        batch_size = len(work) if batch else 1
        for (i, _, manifest, adapter_seconds, _), result in zip(todo, results):
            out[i] = self._respond(result, manifest, adapter_seconds, batch_size)
        return out

    def _prepare(self, payload: dict):
        try:
            request = QwenRequest.model_validate(payload)
        except ValidationError as exc:
            return self._reject("invalid_request", f"{len(exc.errors())} validation error(s)")
        if (request.model, request.revision) != (MODEL_ID, MODEL_REVISION):
            return self._reject("model_revision_mismatch", "requested model/revision is not the pinned checkpoint")
        if request.adapter is None:
            return request, None, 0.0, None
        try:
            manifest, directory = self.resolver.resolve(request.adapter)
            adapter_seconds = self._ensure_adapter(manifest, directory)
        except ArtifactError as exc:
            return self._reject(exc.code, str(exc))
        except Exception as exc:  # load failure: never answer from the base model instead
            return self._reject("adapter_load_failed", type(exc).__name__)
        return request, manifest, adapter_seconds, manifest.checkpoint_id

    def _generate_one(self, request: QwenRequest, adapter: str | None):
        try:
            return self.engine.generate(request, adapter)
        except InputTooLong as exc:
            return exc

    def _respond(self, out, manifest: ArtifactManifest | None, adapter_seconds: float, batch_size: int) -> dict:
        if isinstance(out, InputTooLong):
            return self._reject("input_too_long", f"input exceeds {MAX_INPUT_TOKENS} tokens")
        load = 0.0 if self._load_reported else self.container_load_seconds
        self._load_reported = True
        fields = dict(raw_output=out.raw_output, input_tokens=out.input_tokens, output_tokens=out.output_tokens,
                      finish_reason=out.finish_reason, model=MODEL_ID, revision=MODEL_REVISION, seed_applied=True,
                      generation_seconds=out.generation_seconds, batch_size=batch_size, container_load_seconds=load)
        if manifest is not None:
            fields |= dict(adapter_run_id=manifest.run_id, adapter_hash=manifest.adapter_hash,
                           training_manifest_hash=manifest.training_manifest_hash, adapter_load_seconds=adapter_seconds)
        return QwenResult(**fields).model_dump(mode="json", exclude_none=True,
                                               exclude={"adapter_load_seconds"} if manifest is None else set())

    @staticmethod
    def _reject(code: str, detail: str) -> dict:
        return QwenRejection(error_code=code, detail=detail[:200]).model_dump(mode="json")


def render_prompt(tokenizer, request: QwenRequest) -> str:
    """The one chat-template rendering every engine uses (and the trainer's data goes through the same template)."""
    messages = [{"role": "system", "content": request.system}, *request.messages]
    return tokenizer.apply_chat_template(messages, tools=request.tools, add_generation_prompt=True, tokenize=False)


class TransformersEngine:
    """Real engine: HF Transformers causal LM (bf16, CUDA only) with PEFT adapters. Base requests use
    `disable_adapter()`, so loading an adapter never changes what the base model answers."""

    def __init__(self, model_path: str, *, device: str = "cuda"):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        if device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("no CUDA device: refusing to serve a 7B model on CPU")
        self.torch, self.device = torch, device
        self.tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True)
        dtype = torch.bfloat16 if device == "cuda" else torch.float32
        kwargs = {"device_map": device} if device == "cuda" else {}
        self.model = AutoModelForCausalLM.from_pretrained(model_path, torch_dtype=dtype, local_files_only=True,
                                                          low_cpu_mem_usage=True, **kwargs).eval()
        self.peft = None
        self.im_end = self.tokenizer.convert_tokens_to_ids("<|im_end|>")

    def load_adapter(self, name: str, directory: Path) -> None:
        from peft import PeftModel
        if self.peft is None:
            self.peft = PeftModel.from_pretrained(self.model, str(directory), adapter_name=name, is_trainable=False)
        else:
            self.peft.load_adapter(str(directory), adapter_name=name, is_trainable=False)
        self.peft.eval()

    def unload_adapter(self, name: str) -> None:
        if self.peft is not None:
            self.peft.delete_adapter(name)

    def generate(self, request: QwenRequest, adapter: str | None) -> EngineOutput:
        torch = self.torch
        inputs = self.tokenizer(render_prompt(self.tokenizer, request), return_tensors="pt").to(self.device)
        if inputs["input_ids"].shape[1] > MAX_INPUT_TOKENS:
            raise InputTooLong
        sampling = request.temperature > 0
        if sampling:
            torch.manual_seed(request.seed)
        if self.device == "cuda":
            torch.cuda.synchronize()
        started = time.perf_counter()
        model = self.peft if self.peft is not None else self.model
        kwargs = dict(do_sample=sampling, max_new_tokens=request.max_new_tokens, pad_token_id=self.tokenizer.eos_token_id,
                      **({"temperature": request.temperature} if sampling else {}))
        with torch.inference_mode():
            if adapter is None and self.peft is not None:
                with self.peft.disable_adapter():
                    out = model.generate(**inputs, **kwargs)
            else:
                if adapter is not None:
                    self.peft.set_adapter(adapter)
                out = model.generate(**inputs, **kwargs)
        if self.device == "cuda":
            torch.cuda.synchronize()
        generated = out[0, inputs["input_ids"].shape[1]:]
        stopped = generated.shape[0] > 0 and int(generated[-1]) in {self.tokenizer.eos_token_id, self.im_end}
        return EngineOutput(raw_output=self.tokenizer.decode(generated, skip_special_tokens=False),
                            input_tokens=int(inputs["input_ids"].shape[1]), output_tokens=int(generated.shape[0]),
                            finish_reason="stop" if stopped else "length", generation_seconds=time.perf_counter() - started)


class VLLMEngine:
    """Serving engine: vLLM with continuous batching, automatic prefix caching (every agent sends the same system prompt
    and tool schemas, so those KV blocks are computed once and shared) and multi-LoRA (each request in a batch may name
    a different adapter; adapter=None runs the pure base model). Prompts use the same `render_prompt` as
    TransformersEngine, so serving sees byte-identical inputs to what training renders."""

    def __init__(self, model_path: str, *, max_lora_rank: int = 64):
        from transformers import AutoTokenizer
        from vllm import LLM
        self.tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True)
        # ponytail: max_lora_rank 64 covers the planner default (16); an adapter trained above it fails at generate time
        self.llm = LLM(model=model_path, dtype="bfloat16", enable_prefix_caching=True, enable_lora=True,
                       max_loras=MAX_LOADED_ADAPTERS, max_lora_rank=max_lora_rank,
                       max_model_len=MAX_INPUT_TOKENS + MAX_NEW_TOKENS_CEILING)
        self.loras: dict[str, object] = {}

    def load_adapter(self, name: str, directory: Path) -> None:
        from vllm.lora.request import LoRARequest
        if name not in self.loras:
            self.loras[name] = LoRARequest(name, len(self.loras) + 1, str(directory))

    def unload_adapter(self, name: str) -> None:
        pass  # vLLM swaps adapters on and off the GPU itself (LRU, max_loras); a LoRARequest is only a handle

    def generate(self, request: QwenRequest, adapter: str | None) -> EngineOutput:
        out = self.generate_batch([(request, adapter)])[0]
        if isinstance(out, InputTooLong):
            raise out
        return out

    def generate_batch(self, work: list[tuple[QwenRequest, str | None]]) -> list[EngineOutput | InputTooLong]:
        from vllm import SamplingParams
        out: list[EngineOutput | InputTooLong] = [InputTooLong()] * len(work)
        live, prompts, params, loras = [], [], [], []
        for i, (request, adapter) in enumerate(work):
            ids = self.tokenizer(render_prompt(self.tokenizer, request))["input_ids"]
            if len(ids) > MAX_INPUT_TOKENS:
                continue
            live.append(i)
            prompts.append({"prompt_token_ids": ids})
            params.append(SamplingParams(temperature=request.temperature, seed=request.seed,
                                         max_tokens=request.max_new_tokens, skip_special_tokens=False))
            loras.append(self.loras[adapter] if adapter is not None else None)
        if not prompts:
            return out
        started = time.perf_counter()
        results = self.llm.generate(prompts, params, lora_request=loras, use_tqdm=False)
        seconds = time.perf_counter() - started
        for i, result in zip(live, results):
            choice = result.outputs[0]
            out[i] = EngineOutput(raw_output=choice.text, input_tokens=len(result.prompt_token_ids),
                                  output_tokens=len(choice.token_ids),
                                  finish_reason="stop" if choice.finish_reason == "stop" else "length",
                                  generation_seconds=seconds)
        return out
