# GRPO reinforcement learning (Agent B) — branch `feat/grpo-rl`

Base: `feat/model-pipeline` @ `25121ff`; merged Agent A (`feat/expert-iteration-loop` through its handoff) and latest `main`.
External spend: **$0**. Nothing deployed or called on Modal. No GRPO-trained Qwen adapter exists.
Knobs and usage: `docs/model-runs/GRPO.md`. Pipeline evidence: `docs/model-runs/grpo-offline-e2e/STATUS.md`.

## Built
| # | Milestone | Where | Status |
|---|---|---|---|
| B1 | Custom GRPO loss on the existing PEFT backend, no TRL, no new dependency | `DECISIONS.md` | done |
| B2 | Reward = fitness, killed/unscored get the floor; group-relative advantage; equal rewards give 0 | `training/rl/advantage.py` | done |
| B3 | Per-turn penalty (invalid schema, ungrounded, kill rule on that turn); mask = SFT assistant tool-call labels | `scoring/step_credit.py`, `training/torch_backend.encode_turns` | done |
| B4 | Clipped ratio + β·k3 KL to the base (adapter disabled, same weights); old log-probs from the rollout checkpoint | `training/rl/loss.py`, `training/torch_backend.py` | done |
| B5 | `--algorithm grpo` through train_lora -> gates -> service -> run_training; rollout shard `crucible-grpo-v1` | `scripts/train_lora.py`, `training/rl/dataset.py`, `training/shard.py`, `training/planning.py` | done |
| B6 | Separate RL approval; refusals: scripted, stale, leakage, group < 2, memory-enabled, no signal | `training/gates.py`, `training/rl/dataset.py` | done |
| B7 | Algorithm switch in the Modal job, same image and pins; enabled set baked into the image | `modal_app/qwen_training.py`, `training/service.py` | done |
| B8 | `--plan-only` cost bound (rollout inference + update budget) and exact env values | `scripts/train_lora.py` (`rl.cost`, `rl.env`) | done |
| B9 | Offline end to end on the real backend, pause + resume, sealed and inspected | `tests/test_rl_e2e.py` | done (pipeline evidence only) |
| B10 | Knob docs | `docs/model-runs/GRPO.md` | done |

## Verified, and how
```
uv run pytest -q                                    # default suite (torch tests skip)
CRUCIBLE_TEST_QWEN_TOKENIZER_DIR=<TOKDIR> uv run --no-project --with torch==2.6.0 --with transformers==4.49.0 \
  --with accelerate==1.4.0 --with peft==0.14.0 --with safetensors==0.5.3 --with huggingface-hub==0.29.3 --with numpy \
  --with pytest --with pydantic --with jsonschema --with fastapi --with httpx --with pyyaml --with modal \
  python -m pytest -q tests/test_rl_torch.py tests/test_training_torch_backend.py tests/test_rl_e2e.py
uv run python -m scripts.secret_scan --env-file "<real .env>"   # 0 findings
```
Real-backend tests cover: KL = 0 at init, LoRA-only gradients, +A raises and -A lowers sequence log-prob, bit-identical adapter
after interrupt + resume, policy adapter as the starting point (and rank/target mismatch refused), e2e from scripted rollouts.

## Contracts
* Entry point (posted as CONTRACT on the board): `scripts.train_lora.main([--algorithm grpo --rollouts ... ])`, same outputs and exit
  codes as SFT, plus `training_plan.json["rl"]` = `{rollout_set_hash, stats, cost, env, deploy_env}` and `rollout_manifest.json`.
* Artifact: unchanged `crucible-adapter-v1`. `hyperparameters.method` is `qlora_grpo` | `lora_grpo`, `hyperparameters.grpo` holds
  every knob and the policy checkpoint, `training_manifest_hash` is the rollout set hash. SFT plan/identity dumps are byte-identical
  to before (`grpo` is omitted when absent).
* `TorchLoraBackend(..., policy_adapter_dir=None)`, `service.execute(..., algorithms=frozenset({"sft"}))` (default stays SFT-only),
  `service.policy_adapter_dir(runs_root, plan)`.

## Still blocked (exact variables; only the human sets them)
`CRUCIBLE_MODAL_TOKEN_ROTATED=1`, `CRUCIBLE_MODAL_BILLING_CONFIRMED=1`, `CRUCIBLE_MODAL_RL_CEILING_USD`,
`CRUCIBLE_MODAL_RL_APPROVED_ROLLOUTS_HASH`, deploy-time `CRUCIBLE_ENABLE_L4_RL=1`, and a payment method on the Modal workspace.
Real rollouts also need the inference gates (`CRUCIBLE_MODAL_APPROVED_CEILING_USD`, `CRUCIBLE_ENABLE_L4_PROBE=1`).

## Open items
* Memory-enabled rollouts are refused until rollouts store their retrieved examples (Agent A's schema note).
* GRPO on Qwen-7B memory/speed is unmeasured; the old/ref log-prob pass adds two forward passes per row before step 1.
