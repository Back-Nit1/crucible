# GRPO on world rollouts

Real RL on the same world and training stack as SFT. One command, `scripts.train_lora --algorithm grpo`. Nothing has run on a
GPU. Everything below marked "verified" was checked offline only (CPU, tiny random Qwen2, real pinned Qwen tokenizer).

## What happens
1. **Rollouts** (`training/rollouts.py`, Agent A): every episode, including killed and low-fitness ones, with `--samples-per-task K`.
   Samples of one task under one checkpoint in one iteration share a `group_id`.
2. **Shard** (`training/rl/dataset.py`, laptop): protected splits are excluded and counted. Refused: scripted rollouts without
   `--allow-scripted-traces`, rollouts from any checkpoint other than the one being updated (`stale_rollouts`), memory-enabled
   rollouts (`inexact_prompt`: their stored prompts omit the retrieved examples), groups under `--min-group-size`, duplicate or
   malformed rollouts, and sets with no signal. Advantages are computed here and sealed into the shard bytes.
3. **Audit**: the rollout set becomes `rollout_manifest.json` (content hash = rollout set hash) and goes through the same
   protected/reference leakage audit as SFT before any plan or launch.
4. **Update** (container): same `run_training`, checkpoints, resume and sealed artifact as SFT. `train_step` uses the GRPO loss.

## Knobs
| Flag | Default | Effect |
|---|---|---|
| `--reward-floor` | `-1` | Reward of a killed or never-scored episode. Otherwise the reward is the episode's fitness (unchanged scorer). |
| `--min-group-size` | `2` | Smallest group accepted. Advantage = `(r - mean_group) / (std_group + 1e-6)`. A group with equal rewards gets 0. |
| step credit | `0.5 / 0.5 / 1.0` | Subtracted from one turn's advantage: invalid schema / ungrounded citation / each kill rule attributed to that turn (`scoring/step_credit.py`). Set in `GRPOConfig.step_credit`. |
| `--clip-epsilon` | `0.2` | PPO clip on the ratio `exp(logp - old_logp)`. |
| `--kl-beta` | `0.04` | Weight of the k3 KL estimate to the base model (same weights, adapter disabled). |
| `--policy-adapter-manifest` | none (base) | Sealed artifact the rollouts came from. The update starts from it. Old log-probs come from it and KL is measured against the base. |
| `--epochs`, `--max-steps`, `--learning-rate` | as SFT | Passes over the rollout set. Old log-probs stay those of the rollout checkpoint. |

Loss per target token (assistant tool-call tokens only, the SFT mask): `-min(ρA, clip(ρ,1±ε)A) + β·(e^{ref-logp} - (ref-logp) - 1)`,
summed and divided by the step's target-token count. Every knob is recorded in the artifact: `hyperparameters.method`
(`qlora_grpo` | `lora_grpo`), `hyperparameters.grpo.*`, `training_manifest_hash` (= rollout set hash) and `data_source_model_version`.
The checkpoint id stays `qwen-lora-<hash>`, so `CheckpointCatalog` and population re-entry work unchanged.

## Verified, and how
| Claim | Check |
|---|---|
| Advantages, floor, zero-variance, step credit | `tests/test_rl_advantage.py` |
| Refusals, determinism, exclusions, container parse | `tests/test_rl_dataset.py` |
| KL = 0 at init, finite loss, gradients reach LoRA only, a +A row gains log-prob and a -A row loses it | `tests/test_rl_torch.py` (real PEFT) |
| Interrupt + resume gives a bit-identical adapter | `tests/test_rl_torch.py::test_grpo_resume_equals_uninterrupted_run` |
| Separate gates, deploy flag, policy-adapter verification | `tests/test_training_gates.py`, `tests/test_training_service.py`, `tests/test_modal_training_module.py` |
| CLI plan / refuse / block / train with a fake transport | `tests/test_train_cli.py` |
| End to end on the real backend | `tests/test_rl_e2e.py`, record in `grpo-offline-e2e/STATUS.md` (pipeline evidence only) |

Not verified: anything on a GPU, Qwen-7B memory or speed with GRPO, and whether GRPO improves the shopper.

## What blocks a real run (all unset today; only the human sets them)
`CRUCIBLE_MODAL_TOKEN_ROTATED=1`, `CRUCIBLE_MODAL_BILLING_CONFIRMED=1`, `CRUCIBLE_MODAL_RL_CEILING_USD=<usd>`,
`CRUCIBLE_MODAL_RL_APPROVED_ROLLOUTS_HASH=<rl.rollout_set_hash from training_plan.json>`, and deploy with
`CRUCIBLE_ENABLE_L4_RL=1 uv run modal deploy modal_app/qwen_training.py`. The SFT approval variables do not unlock GRPO,
and the GRPO variables do not unlock SFT. `--plan-only` prints the exact values and the cost bound (`rl.cost`).

## Known limits
* LoRA dropout is 0 for GRPO (an explicit non-zero value is refused): old log-probs are taken without dropout, so dropout
  would move the ratio and KL before any update.
* A group is Agent A's `group_id` = task x checkpoint x iteration, so it pools every genome on that task: the baseline is the
  population's reward on the task, and each row is scored under its own exact system prompt. Strict per-prompt GRPO groups
  would key on genome too; with today's deterministic scripted shopper those would all be zero variance.
* Step credit for invalid or ungrounded calls rarely fires today: the executor rejects such an action before recording it,
  so the episode ends without the offending turn in the rollout (asked of Agent A on the board). Kill-rule credit on the
  terminal turn does fire.
* Old log-probs are computed after the fact from the rollout checkpoint at temperature 1. Rollouts sampled at another
  temperature are slightly off-policy.
* Memory-enabled genomes cannot be trained on until rollouts store their retrieved examples.
* Old and reference log-probs for the whole shard are held in memory. Fine for hundreds of rollouts. Stream them if that changes.
