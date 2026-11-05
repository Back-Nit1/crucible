# Runbook: first real expert iterations

Everything below spends money only after **you** set the gate variables. Until then every command stops with exit 3
and names the variable it needs. Pass the env file with `--env-file`; never copy it into the repo.
`ENV=/Users/nityanthmaramreddy/Downloads/Crucible\ /.env` (the directory name ends in a space).

## 0. Prove the chain offline ($0)

```bash
unset VIRTUAL_ENV; uv sync
uv run python -m scripts.run_loop --iteration-id dry-1 --dry-run            # scripted, synthetic: pipeline evidence only
```

## 1. One-time human steps (Modal dashboard + env file)

1. Add a payment method to the Modal workspace and set a workspace **budget** (hard outer cap), e.g. $10.
2. Rotate the Modal token (`uv run modal token new`), then put in the env file: `CRUCIBLE_MODAL_TOKEN_ROTATED=1`,
   `CRUCIBLE_MODAL_BILLING_CONFIRMED=1`.
3. Print this iteration's bounds and the exact values to set:
   `uv run python -m scripts.run_loop --iteration-id it-1 --plan --population 2 --tasks 4 --seconds-per-call 120`
   Approve and set `CRUCIBLE_MODAL_APPROVED_CEILING_USD` (inference). The recorded probe ceiling is `$0.861948`;
   anything larger is a new approval. The client stops at the ceiling and a rerun resumes, so a lower value only
   splits the work.
4. Deploy inference (and stop it afterwards):
   `CRUCIBLE_ENABLE_L4_PROBE=1 uv run modal deploy modal_app/qwen_inference.py`

## 2. Iteration 1 (SFT)

```bash
uv run python -m scripts.run_loop --iteration-id it-1 --population 2 --tasks 4 --env-file "$ENV"
# stops at train (exit 3). Read checkpoints/loop/it-1/stages/curate.json, then set:
#   CRUCIBLE_MODAL_TRAINING_APPROVED_MANIFEST_HASH=<training_manifest_hash>
#   CRUCIBLE_MODAL_TRAINING_CEILING_USD=0.20      # smoke size: docs/model-runs/GPU_READINESS.md
CRUCIBLE_ENABLE_L4_TRAIN=1 uv run modal deploy modal_app/qwen_training.py
uv run python -m scripts.run_loop --iteration-id it-1 --population 2 --tasks 4 --max-steps 4 --env-file "$ENV"   # resumes at train
uv run modal app stop crucible-qwen-training
```

The loop then evaluates base vs the SFT adapter on the protected task set and writes the re-entry command to
`stages/reenter.json`. A stage that pauses (budget reached, generation interrupted) exits 0; rerun the same command.

## 3. Iteration 2 (GRPO on the SFT adapter)

Needs Agent B's GRPO trainer on `main`. Groups need at least 2 samples per task.

```bash
uv run python -m scripts.run_loop --iteration-id it-2 --algorithm grpo --samples-per-task 4 --population 2 --tasks 4 \
  --adapter-manifest checkpoints/loop/it-1/train/artifact_manifest.json --plan        # bounds + values
uv run python -m scripts.run_loop --iteration-id it-2 --algorithm grpo --samples-per-task 4 --population 2 --tasks 4 \
  --adapter-manifest checkpoints/loop/it-1/train/artifact_manifest.json --env-file "$ENV"
# stops at train (exit 3): set CRUCIBLE_MODAL_RL_APPROVED_ROLLOUTS_HASH=<from stages/plan.json> and CRUCIBLE_MODAL_RL_CEILING_USD
CRUCIBLE_ENABLE_L4_RL=1 uv run modal deploy modal_app/qwen_training.py
uv run python -m scripts.run_loop ... same command ...                                 # resumes at train
uv run modal app stop crucible-qwen-training; uv run modal app stop crucible-qwen-inference
```

## Stop / inspect

- Stop before the next stage: `touch checkpoints/loop/STOP` (exit 4); delete it and rerun to resume.
- Status: `GET /loop/status` (API) or the loop panel on `/system` (web).
- Always `uv run modal app stop ...` when done; check the Modal dashboard bill, which is authoritative.
