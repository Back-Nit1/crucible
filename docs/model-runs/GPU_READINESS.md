# GPU readiness (static, no GPU used)

Everything here is checked without a GPU and without Modal. Numbers marked *estimate* are arithmetic, not
measurements; the first smoke run replaces them. Nothing on this page has run on an L4.

## Image pins

`tests/test_gpu_readiness.py` fails if the pins in `modal_app/qwen_inference.py` or `modal_app/qwen_training.py`
drift from these blocks.

Inference image (`modal_app/qwen_inference.py`, vLLM engine; vLLM pins its own torch/transformers). This image has
not been built or deployed yet: the first `modal deploy` is the build check.

```pins-inference
jsonschema==4.23.0
pydantic==2.14.2
transformers==5.19.0
vllm==0.32.0
```

Training image (`modal_app/qwen_training.py` `TRAIN_PINS`):

```pins-training
accelerate==1.15.0
bitsandbytes==0.50.2
huggingface-hub==2.2.0
jsonschema==4.23.0
peft==0.21.2
pydantic==2.14.2
safetensors==0.8.0
torch==2.13.0
transformers==5.19.0
```

Resolution check (2026-11-08, PyPI metadata only): both sets resolve for the Modal image platform with
`uv pip compile <pins> --python-platform x86_64-manylinux_2_28 --python-version 3.12` (66 packages for training,
198 for inference). Both use `torch==2.13.0` (CUDA 13.0 wheels: `nvidia-cuda-runtime==13.0.96`,
`nvidia-cublas==13.1.1.3`, `nvidia-cudnn-cu13==9.20.0.48`, `triton==3.7.1`) and `transformers==5.19.0`, so training
and serving share one tokenizer/chat-template implementation.

Security bump (2026-11-08): the previous pins (`torch==2.6.0`, `transformers==4.49.0`/`4.55.4`, `vllm==0.10.1.1`) had
over 90 published advisories in `pip-audit`; the current sets have none. The real-library CPU tests
(`tests/test_training_torch_backend.py`, `tests/test_rl_e2e.py`: tiny Qwen2 + real Qwen2.5 tokenizer, LoRA train,
resume, adapter load) pass on both the old and the new pins (6/6 each). Not verified: CUDA discovery inside the Modal
container, that Modal's L4 driver supports CUDA 13, and bitsandbytes 0.50.2 NF4 on the GPU (CPU tests run without
quantization). The 2026-11 base probe ran on the old inference image; rerun it once on the new one.

## QLoRA memory at seq 2048 on L4 (24 GB) — estimate

Qwen2.5-7B-Instruct: 28 layers, hidden 3584, MLP 18944, 28 query / 4 KV heads, vocab 152064, untied embeddings.
Settings from `training/torch_backend.py` + `LoRAHyperparameters` defaults: NF4 double-quant, bf16 compute,
gradient checkpointing, micro-batch 1, rank 16 on all 7 projections, AdamW.

| Item | Arithmetic | GB |
|---|---|---:|
| NF4 linear weights | 6.53 B params × 0.5 B + quant constants | 3.4 |
| `embed_tokens` + `lm_head` in fp32 | 2 × 152064 × 3584 × 4 B (`prepare_model_for_kbit_training` upcasts them) | 4.4 |
| LoRA params + grads + AdamW (fp32) | 40.4 M × 16 B | 0.65 |
| Checkpointed layer inputs | 28 × 2048 × 3584 × 2 B | 0.41 |
| One layer recompute (eager attn fp32 scores ×3, MLP, dequant temp) | 28 × 2048² × 4 B × 3 + ~0.6 | 2.0 |
| Logits + fp32 loss + logit grads | 2048 × 152064 × (2 + 4 + 4) B | 3.1 |
| CUDA context + allocator slack | | 1.0 |
| **Total** | | **≈ 15** |

L4 usable ≈ 22.5 GB, so about 7 GB of headroom at the 2048 cap. `encode_example` refuses longer examples
(`example_too_long`) instead of truncating, so the cap is never silently exceeded.

## Wall-clock budget math

- Rate: L4 + 2 CPU + 32 GiB at recorded list rates = **$0.00031924/s** (`training.gates.cost_per_second`).
- Per launch hard stop: `MAX_LAUNCH_SECONDS` = 2580 s ($0.82) under the 45-min Modal timeout ($0.86 = the recorded
  probe ceiling).
- `--max-cost 0.50` buys 1566 s; the trainer soft-stops at that budget and the same run id resumes.
- Step time *estimate*: 6 × 7.6 B × 16384 tokens (8 × 2048) ≈ 7.5e14 FLOP/step; at ~30 % of L4's ~121 TFLOPS
  bf16 and ~1.5× NF4 dequant overhead ≈ **30 s/step** at full length (shorter examples are faster).
  So $0.50 ≈ 50 full-length steps after load. Model load time is **not measured**.

## Smoke-run plan

Smallest sensible ceiling: **$0.20** (626 s at list rates: room for an unmeasured model load plus 2 steps; the gate
refuses anything that buys under 60 s).

```bash
uv run python -m scripts.run_loop --iteration-id it-1 --plan            # prints the exact values below
export CRUCIBLE_MODAL_TRAINING_CEILING_USD=0.20
export CRUCIBLE_MODAL_TRAINING_APPROVED_MANIFEST_HASH=<training_manifest_hash from stages/curate.json>
CRUCIBLE_ENABLE_L4_TRAIN=1 uv run modal deploy modal_app/qwen_training.py
uv run python -m scripts.train_lora --records <gen>/sft.jsonl --manifest <gen>/training_manifest.json \
  --run-id it-1-smoke --max-cost 0.20 --max-steps 4 --stop-after-steps 2 --launch --env-file <ENV_FILE>
uv run modal app stop crucible-qwen-training
```

Record from the smoke run: model load seconds, seconds per step, peak `torch.cuda.max_memory_allocated`, measured
cost. Then replace the estimates above.
