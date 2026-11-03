"""Production LoRA / QLoRA backend (PyTorch + Transformers + PEFT [+ bitsandbytes]). Imported lazily: nothing in the
offline suite needs torch, and the CPU-only laptop path refuses to build a 7B model (see `require_cuda_for_large`).

Pinned library set (also the Modal image pins; see modal_app.qwen_training.TRAIN_PINS):
  torch 2.6.0, transformers 4.49.0, accelerate 1.4.0, peft 0.14.0, bitsandbytes 0.45.3 (linux/CUDA only).

Every piece of mutable training state is captured and restored: PEFT adapter weights, AdamW moments, scheduler
position, torch CPU+CUDA RNG. Loss is token-level over the assistant tool-call turns only."""
from __future__ import annotations

import importlib.metadata as md
import json
import random
from collections.abc import Sequence
from pathlib import Path

from training.planning import LoRAHyperparameters
from training.shard import Shard

STATE_FILE = "trainer_state.pt"
ADAPTER_SUBDIR = "adapter"
IGNORE_INDEX = -100


class BackendError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code


def backend_signature() -> str:
    """Library versions a checkpoint was written under; resuming under different ones is refused by the run identity."""
    def v(name: str) -> str:
        try:
            return md.version(name)
        except md.PackageNotFoundError:
            return "absent"
    return ",".join(f"{n}=={v(n)}" for n in ("torch", "transformers", "peft", "accelerate", "bitsandbytes"))


def encode_example(tokenizer, system: str, tools: list[dict], messages: list[dict], max_length: int) -> tuple[list[int], list[int]]:
    """Chat-template render of the whole episode with labels ONLY on assistant turns (tool calls + <|im_end|>).
    Spans come from re-rendering the template prefix by prefix, so they follow the exact inference-time format."""
    full_messages = [{"role": "system", "content": system}, *messages]
    render = lambda msgs, gen: tokenizer.apply_chat_template(msgs, tools=tools, add_generation_prompt=gen, tokenize=False)
    text = render(full_messages, False)
    spans: list[tuple[int, int]] = []
    for i, message in enumerate(full_messages):
        if message["role"] != "assistant":
            continue
        start_text, end_text = render(full_messages[:i], True), render(full_messages[:i + 1], False)
        if not (text.startswith(end_text) and end_text.startswith(start_text)):
            raise BackendError("template_not_prefix_stable", "chat template does not render turns incrementally")
        spans.append((len(start_text), len(end_text.rstrip("\n"))))
    if not spans:
        raise BackendError("no_assistant_turns", "example has no assistant turn to learn from")
    enc = tokenizer(text, add_special_tokens=False, return_offsets_mapping=True)
    ids = list(enc["input_ids"])
    if len(ids) > max_length:
        raise BackendError("example_too_long", f"{len(ids)} tokens exceeds max_sequence_length {max_length}")
    labels = [tok if any(s <= a and b <= e for s, e in spans) else IGNORE_INDEX
              for tok, (a, b) in zip(ids, enc["offset_mapping"])]
    if all(label == IGNORE_INDEX for label in labels):
        raise BackendError("no_target_tokens", "no tokens fall inside an assistant turn")
    return ids, labels


class TorchLoraBackend:
    def __init__(self, *, model, tokenizer, shard: Shard, hp: LoRAHyperparameters, total_steps: int, device: str):
        import torch
        from peft import LoraConfig, get_peft_model
        from transformers import get_cosine_schedule_with_warmup
        self.torch, self.hp, self.device = torch, hp, device
        self.encoded = [encode_example(tokenizer, shard.system, shard.tools, ex, hp.max_sequence_length)
                        for ex in shard.examples]
        torch.manual_seed(hp.seed)
        random.seed(hp.seed)
        config = LoraConfig(r=hp.lora_rank, lora_alpha=hp.lora_alpha, lora_dropout=float(hp.lora_dropout), bias="none",
                            target_modules=list(hp.target_modules), task_type="CAUSAL_LM")
        self.model = get_peft_model(model, config)
        self.model.config.use_cache = False
        params = [p for p in self.model.parameters() if p.requires_grad]
        self.optimizer = torch.optim.AdamW(params, lr=float(hp.learning_rate), weight_decay=float(hp.weight_decay))
        self.scheduler = get_cosine_schedule_with_warmup(self.optimizer, hp.warmup_steps, total_steps)

    # -- training ---------------------------------------------------------------------------------------------------
    def train_step(self, example_indices: Sequence[int]) -> float:
        torch, hp = self.torch, self.hp
        self.model.train()
        self.optimizer.zero_grad(set_to_none=True)
        targets = sum(sum(1 for t in self.encoded[i][1][1:] if t != IGNORE_INDEX) for i in example_indices)
        total = 0.0
        for start in range(0, len(example_indices), hp.micro_batch_size):
            chunk = [self.encoded[i] for i in example_indices[start:start + hp.micro_batch_size]]
            width = max(len(ids) for ids, _ in chunk)
            pad = 0
            input_ids = torch.tensor([ids + [pad] * (width - len(ids)) for ids, _ in chunk], device=self.device)
            labels = torch.tensor([lab + [IGNORE_INDEX] * (width - len(lab)) for _, lab in chunk], device=self.device)
            mask = torch.tensor([[1] * len(ids) + [0] * (width - len(ids)) for ids, _ in chunk], device=self.device)
            with torch.autocast(device_type=self.device.split(":")[0], dtype=torch.bfloat16, enabled=self.device != "cpu"):
                logits = self.model(input_ids=input_ids, attention_mask=mask).logits
            loss = torch.nn.functional.cross_entropy(
                logits[:, :-1].float().reshape(-1, logits.size(-1)), labels[:, 1:].reshape(-1),
                ignore_index=IGNORE_INDEX, reduction="sum") / targets
            loss.backward()
            total += float(loss.detach())
        torch.nn.utils.clip_grad_norm_([p for p in self.model.parameters() if p.requires_grad], float(hp.max_grad_norm))
        self.optimizer.step()
        self.scheduler.step()
        return total

    # -- checkpointing ----------------------------------------------------------------------------------------------
    def capture(self, directory: Path) -> None:
        torch = self.torch
        self.model.save_pretrained(directory / ADAPTER_SUBDIR)  # adapter weights only (PEFT never writes the base)
        (directory / ADAPTER_SUBDIR / "README.md").unlink(missing_ok=True)
        state = {"optimizer": self.optimizer.state_dict(), "scheduler": self.scheduler.state_dict(),
                 "rng_cpu": torch.get_rng_state(),
                 "rng_cuda": torch.cuda.get_rng_state_all() if torch.cuda.is_available() else []}
        torch.save(state, directory / STATE_FILE)
        (directory / "python_rng.json").write_text(json.dumps(random.getstate()))

    def restore(self, directory: Path) -> None:
        torch = self.torch
        from peft import set_peft_model_state_dict
        from safetensors.torch import load_file
        adapter = load_file(str(directory / ADAPTER_SUBDIR / "adapter_model.safetensors"))
        result = set_peft_model_state_dict(self.model, adapter)
        if getattr(result, "unexpected_keys", None):
            raise BackendError("adapter_keys_mismatch", "checkpoint adapter has unexpected keys for this model")
        state = torch.load(directory / STATE_FILE, map_location="cpu", weights_only=True)  # tensors/primitives only
        self.optimizer.load_state_dict(state["optimizer"])
        self.scheduler.load_state_dict(state["scheduler"])
        torch.set_rng_state(state["rng_cpu"])
        if state["rng_cuda"] and torch.cuda.is_available():
            torch.cuda.set_rng_state_all(state["rng_cuda"])
        version, internal, gauss = json.loads((directory / "python_rng.json").read_text())
        random.setstate((version, tuple(internal), gauss))

    def export_adapter(self, directory: Path) -> None:
        self.model.save_pretrained(directory)
        (directory / "README.md").unlink(missing_ok=True)


def load_base_model(model_path: str, hp: LoRAHyperparameters, *, device: str, require_cuda_for_large: bool = True):
    """Load the pinned base model from a local snapshot. Never silently degrades: a 7B model on CPU is refused."""
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    if device == "cpu" and (require_cuda_for_large or hp.quantization == "nf4"):
        raise BackendError("cpu_refused", "refusing to train a large or 4-bit model on CPU")
    if device != "cpu" and not torch.cuda.is_available():
        raise BackendError("no_cuda", "CUDA requested but unavailable; no CPU fallback")
    tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True)
    kwargs: dict = {"local_files_only": True, "torch_dtype": torch.bfloat16 if device != "cpu" else torch.float32}
    if hp.quantization == "nf4":
        kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=torch.bfloat16)
        kwargs["device_map"] = {"": 0}
    elif device != "cpu":
        kwargs["device_map"] = {"": 0}
    model = AutoModelForCausalLM.from_pretrained(model_path, **kwargs)
    if hp.quantization == "nf4":
        from peft import prepare_model_for_kbit_training
        model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
    else:
        model.gradient_checkpointing_enable()
        model.enable_input_require_grads()
    return model, tokenizer
