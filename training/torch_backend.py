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


def encode_turns(tokenizer, system: str, tools: list[dict], messages: list[dict],
                 max_length: int) -> tuple[list[int], list[int], list[int]]:
    """Chat-template render of the whole episode with labels ONLY on assistant turns (tool calls + <|im_end|>), plus
    the assistant-turn index of every token (-1 outside assistant turns). Spans come from re-rendering the template
    prefix by prefix, so they follow the exact inference-time format."""
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
    turns = [next((j for j, (s, e) in enumerate(spans) if s <= a and b <= e), -1) for a, b in enc["offset_mapping"]]
    labels = [tok if turn >= 0 else IGNORE_INDEX for tok, turn in zip(ids, turns)]
    if all(label == IGNORE_INDEX for label in labels):
        raise BackendError("no_target_tokens", "no tokens fall inside an assistant turn")
    return ids, labels, turns


class TorchLoraBackend:
    def __init__(self, *, model, tokenizer, shard: Shard, hp: LoRAHyperparameters, total_steps: int, device: str,
                 policy_adapter_dir: Path | None = None):
        """GRPO (hp.grpo set): `policy_adapter_dir` holds the verified adapter the rollouts came from (None = base). Old
        and reference log-probs are computed here, before any update or checkpoint restore, so a resumed run rebuilds
        exactly the same ones."""
        import torch
        from peft import LoraConfig, get_peft_model
        from transformers import get_cosine_schedule_with_warmup
        self.torch, self.hp, self.device = torch, hp, device
        systems = shard.example_systems or [shard.system] * len(shard.examples)
        encoded = [encode_turns(tokenizer, system, shard.tools, ex, hp.max_sequence_length)
                   for system, ex in zip(systems, shard.examples)]
        self.encoded = [(ids, labels) for ids, labels, _ in encoded]
        if (hp.grpo is None) != (shard.turn_advantages is None) or (policy_adapter_dir and hp.grpo is None):
            raise BackendError("algorithm_shard_mismatch", "GRPO needs a crucible-grpo-v1 shard and SFT an SFT shard")
        torch.manual_seed(hp.seed)
        random.seed(hp.seed)
        config = LoraConfig(r=hp.lora_rank, lora_alpha=hp.lora_alpha, lora_dropout=float(hp.lora_dropout), bias="none",
                            target_modules=list(hp.target_modules), task_type="CAUSAL_LM")
        self.model = get_peft_model(model, config)
        self.model.config.use_cache = False
        params = [p for p in self.model.parameters() if p.requires_grad]
        self.optimizer = torch.optim.AdamW(params, lr=float(hp.learning_rate), weight_decay=float(hp.weight_decay))
        self.scheduler = get_cosine_schedule_with_warmup(self.optimizer, hp.warmup_steps, total_steps)
        if hp.grpo is not None:
            if policy_adapter_dir is not None:
                config = json.loads((policy_adapter_dir / "adapter_config.json").read_text())
                if (config.get("r"), config.get("lora_alpha"), set(config.get("target_modules") or ())) != (
                        hp.lora_rank, hp.lora_alpha, set(hp.target_modules)):
                    raise BackendError("policy_adapter_incompatible", "policy adapter rank/alpha/targets differ from this run's LoRA")
                self._load_adapter(policy_adapter_dir / "adapter_model.safetensors")
            # per example, aligned with labels[1:]: advantage of the turn each predicted token belongs to
            self.token_advantages = [[adv[t] if t >= 0 else 0.0 for t in turns[1:]]
                                     for (_, _, turns), adv in zip(encoded, shard.turn_advantages)]
            self.old_logp = self._frozen_logprobs(adapter=True)    # rollout checkpoint
            self.ref_logp = self._frozen_logprobs(adapter=False)   # base: same weights, adapter disabled

    # -- GRPO helpers -----------------------------------------------------------------------------------------------
    def _token_logprobs(self, input_ids, labels, mask):
        """Log-prob of labels[:, 1:] as [B, L-1], 0 where unlabeled. Logits are computed only at positions that predict a
        labeled token (`logits_to_keep`): a full 8192 x 152064 fp32 matrix, its bf16 copy and its grad are ~12 GB on a 24 GB L4."""
        torch = self.torch
        target = labels[:, 1:]
        keep = (target != IGNORE_INDEX).any(0).nonzero().squeeze(1)  # union over the micro-batch rows
        with torch.autocast(device_type=self.device.split(":")[0], dtype=torch.bfloat16, enabled=self.device != "cpu"):
            logits = self.model(input_ids=input_ids, attention_mask=mask, logits_to_keep=keep).logits
        logp = -torch.nn.functional.cross_entropy(logits.float().transpose(1, 2), target[:, keep],
                                                  ignore_index=IGNORE_INDEX, reduction="none")
        return torch.zeros(target.shape, device=logp.device, dtype=logp.dtype).index_copy(1, keep, logp)

    def _frozen_logprobs(self, *, adapter: bool) -> list[list[float]]:
        import contextlib
        torch = self.torch
        self.model.eval()
        out = []
        with torch.no_grad(), (contextlib.nullcontext() if adapter else self.model.disable_adapter()):
            for ids, labels in self.encoded:
                t = lambda rows: torch.tensor([rows], device=self.device)
                out.append(self._token_logprobs(t(ids), t(labels), t([1] * len(ids)))[0].cpu().tolist())
        return out

    def _load_adapter(self, weights: Path) -> None:
        from peft import set_peft_model_state_dict
        from safetensors.torch import load_file
        result = set_peft_model_state_dict(self.model, load_file(str(weights)))
        if getattr(result, "unexpected_keys", None):
            raise BackendError("adapter_keys_mismatch", "checkpoint adapter has unexpected keys for this model")

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
            if hp.grpo is None:
                loss = -self._token_logprobs(input_ids, labels, mask).sum() / targets
            else:
                from training.rl.loss import grpo_token_loss
                idx = example_indices[start:start + hp.micro_batch_size]
                rows = lambda per: torch.tensor([per[i] + [0.0] * (width - 1 - len(per[i])) for i in idx], device=self.device)
                loss = grpo_token_loss(self._token_logprobs(input_ids, labels, mask), rows(self.old_logp), rows(self.ref_logp),
                                       rows(self.token_advantages), (labels[:, 1:] != IGNORE_INDEX).float(),
                                       clip_epsilon=float(hp.grpo.clip_epsilon), kl_beta=float(hp.grpo.kl_beta)) / targets
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
        self._load_adapter(directory / ADAPTER_SUBDIR / "adapter_model.safetensors")
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
    # sdpa (never eager): eager materialises fp32 [heads, L, L] scores, 2.7 GiB per layer at 5k tokens and an OOM on the first L4 run.
    kwargs: dict = {"local_files_only": True, "dtype": torch.bfloat16 if device != "cpu" else torch.float32,
                    "attn_implementation": "sdpa"}
    if hp.quantization == "nf4":
        kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=torch.bfloat16)
        kwargs["device_map"] = {"": 0}
    elif device != "cpu":
        kwargs["device_map"] = {"": 0}
    model = AutoModelForCausalLM.from_pretrained(model_path, **kwargs)
    # Not prepare_model_for_kbit_training: it upcasts embed_tokens + lm_head to fp32 (+4.4 GB on a 7B) for no benefit under bf16 autocast.
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    model.enable_input_require_grads()
    return model, tokenizer
