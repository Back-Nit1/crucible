# GRPO reinforcement learning (Agent B) — branch `feat/grpo-rl`

Base: `feat/model-pipeline` @ `25121ff` (== main). External spend: **$0**. Nothing deployed or called on Modal.

## Plan (milestones; status updated as they land)
| # | Milestone | Where | Status |
|---|---|---|---|
| B1 | Decision: custom GRPO loss on the existing PEFT backend, no TRL | `DECISIONS.md` | in progress |
| B2 | Episode reward (fitness, killed floor) + group-relative advantage | `training/rl/advantage.py` | todo |
| B3 | Per-turn credit from turn flags; mask = assistant tool-call tokens | `scoring/step_credit.py`, `training/rl/advantage.py` | todo |
| B4 | Clipped-ratio loss + k3 KL to base (adapter disabled, same weights) | `training/rl/loss.py` | todo |
| B5 | `--algorithm grpo` through train_lora -> service -> run_training; resume bit-identical | `scripts/train_lora.py`, `training/*` | todo |
| B6 | RL gates (`CRUCIBLE_MODAL_RL_*`, `CRUCIBLE_ENABLE_L4_RL`), stale/scripted/group refusals | `training/gates.py` | todo |
| B7 | Algorithm switch in the Modal job (same image/pins) | `modal_app/qwen_training.py` | todo |
| B8 | `--plan-only` cost: K x tasks x episode seconds + update budget | `scripts/train_lora.py` | todo |
| B9 | Offline end to end on tiny Qwen2 (pipeline evidence only) | `docs/model-runs/` | todo |
| B10 | Knob docs | `docs/model-runs/GRPO.md` | todo |

## Shape (one sentence each)
* Laptop: rollouts.jsonl (all episodes, K per task) -> refusals -> per-turn advantages -> content-addressed `crucible-grpo-v1` shard.
* Container: same `run_training` / `CheckpointStore` / `finalize_artifact`; the backend's `train_step` switches loss on `hp.algorithm`.
* Old log-probs and reference log-probs are computed once when the backend is built (before any restore), i.e. from the rollout
  checkpoint and from the base with the adapter disabled; resume rebuilds them identically.
