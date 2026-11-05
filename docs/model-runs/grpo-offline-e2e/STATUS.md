# GRPO offline end to end — pipeline evidence only

Run 2026-11-05 on a laptop CPU. **Not a model-quality result.** The rollouts come from the scripted oracle shopper (it reads
the answer key) on the synthetic test catalog, and the model is a 2-layer randomly initialised Qwen2 with the real pinned
Qwen tokenizer. No Modal function was deployed or called; external spend **$0**.

What it proves (`tests/test_rl_e2e.py`, one test):
scripted world generation with `--samples-per-task 2` -> `rollouts.jsonl` -> `train_lora --algorithm grpo --plan-only`
(refused without `--allow-scripted-traces`, planned with it; leakage audit re-run on the rollout set) -> the sealed
`crucible-grpo-v1` shard -> real PEFT backend, interrupted after step 1 and resumed -> sealed `crucible-adapter-v1` artifact ->
`scripts.inspect_training_artifact` verifies manifest and adapter files.

Observed (seed 20261105, population 4, 4 tasks, K=2):

| | value |
|---|---|
| rollouts used / excluded (protected split) | 24 / 8 |
| groups / zero-variance groups | 3 / 0 |
| shard rows | 24 |
| rollout set hash | `15f1aa3db7445a7f9cc040b3a059084b13d3fa1e9e6789b7b5e65570c7c78cd3` |
| dataset hash | `d92da72a553e6a0ef22ce69f92ee4df6044f81a3d571bd107ecddb7dd59a285d` |
| steps / launches | 2 / 2 (pause + resume) |
| losses | -0.2294, -0.2294 (step 1 is -A of the sampled row at ratio 1) |
| artifact | `qwen-lora-b5102f233f5c`, `hyperparameters.method = lora_grpo`, `data_source_model_version = scripted-v1` |

The tiny run swaps only the LoRA shape (r4, q/v) and the base (`tiny/qwen2-random`) and records that in its own plan hash;
the rollout set, shard bytes and GRPO knobs are the ones `train_lora` planned. The adapter is meaningless as a policy.

Found while running it: the scripted oracle alone (population 2, no fixture genomes) gives every group equal rewards, which
is correctly refused as `no_signal`; before `92059a5` a repeating-decimal fitness made such groups look like
1e-22 advantages instead of 0.

Reproduce (downloads ~11 MB of public tokenizer files once; see docs/handoffs/modal-training-runtime.md):

```bash
CRUCIBLE_TEST_QWEN_TOKENIZER_DIR=<TOKDIR> uv run --no-project --with torch==2.6.0 --with transformers==4.49.0 \
  --with accelerate==1.4.0 --with peft==0.14.0 --with safetensors==0.5.3 --with huggingface-hub==0.29.3 --with numpy \
  --with pytest --with pydantic --with jsonschema --with fastapi --with httpx --with pyyaml --with modal \
  python -m pytest -q -s tests/test_rl_e2e.py
```
