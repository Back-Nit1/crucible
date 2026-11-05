# Expert-iteration loop (Agent A, `feat/expert-iteration-loop`)

Goal: one resumable command runs real model rollouts -> curation -> leakage audit -> gated LoRA training -> gated
evaluation -> adapter re-enters the population, keeping every episode as rollout data. No money is spent: every stage
is verified offline; paid stages stop at the first missing gate variable (exit 3).

## Milestones

| # | What | Status |
|---|---|---|
| A1 | `training/rollouts.py` `RolloutRecord` (schema owner A) | done `bee10d0` |
| A2 | `rollouts.jsonl` for every episode + `curation_report.json` drop counts | done `3fd933a` |
| A3 | `run_generation --samples-per-task K` (group sampling, resume-safe) | todo |
| A4 | `scripts/run_loop.py` stages + status JSON + resume + gates (exit 3) + `--dry-run` | todo |
| A5 | `run_loop --plan` per-stage max cost + exact env vars | todo |
| A6 | `run_evaluation` contenders base / SFT / GRPO with fitness + kill-rate deltas | todo |
| A7 | GPU readiness: pins test, L4 memory math, wall-clock budget, smoke plan | todo |
| A8 | Inference retries/timeouts (transient codes only), episode wall-clock cap, kill switch | todo |
| A9 | `GET /loop/status` + web panel | todo |
| A10 | `docs/model-runs/RUNBOOK.md` | todo |
| A11 | `--algorithm grpo` wired to Agent B's CONTRACT | todo |

## Notes
- Rollout turn prompts are rebuilt with `agents.model.render_messages` (the policy's own renderer). Retrieved memory
  examples are not stored on episodes, so memory-enabled prompts omit them.
- Kill rules are episode-level; a rollout attributes them to the terminal turn.
- `scripted=True` rollouts are pipeline evidence only.
