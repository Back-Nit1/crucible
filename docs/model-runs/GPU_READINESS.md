# GPU readiness (static, no GPU used)

Everything here is checked without a GPU and without Modal. Numbers marked *estimate* are arithmetic, not
measurements; the first smoke run replaces them. Nothing on this page has run on an L4.

## Image pins

`tests/test_gpu_readiness.py` fails if the pins in `modal_app/qwen_inference.py` or `modal_app/qwen_training.py`
drift from these blocks.

Inference image (`modal_app/qwen_inference.py`):

```pins-inference
accelerate==1.4.0
huggingface-hub==0.29.3
jsonschema==4.23.0
peft==0.14.0
pydantic==2.14.2
safetensors==0.5.3
torch==2.6.0
transformers==4.49.0
```

Training image (`modal_app/qwen_training.py` `TRAIN_PINS`):

```pins-training
accelerate==1.4.0
bitsandbytes==0.45.3
huggingface-hub==0.29.3
jsonschema==4.23.0
peft==0.14.0
pydantic==2.14.2
safetensors==0.5.3
torch==2.6.0
transformers==4.49.0
```

Resolution check (2026-11-04, PyPI metadata only): both sets resolve for the Modal image platform with
`uv pip compile <pins> --python-platform x86_64-manylinux_2_28 --python-version 3.12` (163 packages for training,
159 for inference). `torch==2.6.0` pulls the CUDA 12.4 wheels (`nvidia-cuda-runtime-cu12==12.4.127`,
`nvidia-cublas-cu12==12.4.5.8`, `nvidia-cudnn-cu12==9.1.0.70`) and `triton==3.2.0`. L4 is Ada (sm_89), which CUDA
12.4 and the bitsandbytes 0.45.3 manylinux wheel support. Not verified: CUDA discovery inside the Modal container.

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
