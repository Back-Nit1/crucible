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
from modal_app.qwen_protocol import MAX_INPUT_TOKENS, QwenRejection, QwenRequest, QwenResult
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
        try:
            request = QwenRequest.model_validate(payload)
        except ValidationError as exc:
            return self._reject("invalid_request", f"{len(exc.errors())} validation error(s)")
        if (request.model, request.revision) != (MODEL_ID, MODEL_REVISION):
            return self._reject("model_revision_mismatch", "requested model/revision is not the pinned checkpoint")
        manifest, adapter_seconds, name = None, 0.0, None
        if request.adapter is not None:
            try:
                manifest, directory = self.resolver.resolve(request.adapter)
                adapter_seconds = self._ensure_adapter(manifest, directory)
            except ArtifactError as exc:
                return self._reject(exc.code, str(exc))
            except Exception as exc:  # load failure: never answer from the base model instead
                return self._reject("adapter_load_failed", type(exc).__name__)
            name = manifest.checkpoint_id
        try:
            out = self.engine.generate(request, name)
        except InputTooLong:
            return self._reject("input_too_long", f"input exceeds {MAX_INPUT_TOKENS} tokens")
        load = 0.0 if self._load_reported else self.container_load_seconds
        self._load_reported = True
        fields = dict(raw_output=out.raw_output, input_tokens=out.input_tokens, output_tokens=out.output_tokens,
                      finish_reason=out.finish_reason, model=MODEL_ID, revision=MODEL_REVISION, seed_applied=True,
                      generation_seconds=out.generation_seconds, container_load_seconds=load)
        if manifest is not None:
            fields |= dict(adapter_run_id=manifest.run_id, adapter_hash=manifest.adapter_hash,
                           training_manifest_hash=manifest.training_manifest_hash, adapter_load_seconds=adapter_seconds)
        return QwenResult(**fields).model_dump(mode="json", exclude_none=True,
                                               exclude={"adapter_load_seconds"} if manifest is None else set())

    @staticmethod
    def _reject(code: str, detail: str) -> dict:
        return QwenRejection(error_code=code, detail=detail[:200]).model_dump(mode="json")


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
        messages = [{"role": "system", "content": request.system}, *request.messages]
        rendered = self.tokenizer.apply_chat_template(messages, tools=request.tools, add_generation_prompt=True,
                                                      tokenize=False)
        inputs = self.tokenizer(rendered, return_tensors="pt").to(self.device)
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
