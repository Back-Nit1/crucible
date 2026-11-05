# Expert-iteration loop (Agent A, `feat/expert-iteration-loop`)

One resumable command runs model rollouts -> curation -> leakage audit -> LoRA plan -> gated train (SFT or GRPO) ->
gated evaluation -> adapter re-entry, and keeps every episode as rollout data. External spend: **$0**. Nothing was
deployed or called on Modal; every stage is verified offline.

## What is built

| # | What | Where | Verified by |
|---|---|---|---|
| A1 | `RolloutRecord` (`crucible-rollout-v1`), one per episode; turn prompts via `agents.model.render_messages` | `training/rollouts.py` | `tests/test_training_rollouts.py` |
| A2 | `rollouts.jsonl` (every episode) + `curation_report.json` (drops per reason), byte-identical reruns | `scripts/run_generation.py`, `modal_app/world_runner.py` | `tests/test_run_generation_cli.py` |
| A3 | `--samples-per-task K`: keys `genome:task#k`, derived seeds, shared `group_id`; K=1 unchanged bytes; other K refused on resume | `world/` | same |
| A4 | `scripts/run_loop.py`: 7 stages, `stages/<stage>.json`, resume, exit 3 naming gate vars, `--dry-run` | `scripts/run_loop.py` | `tests/test_run_loop.py` |
| A5 | `run_loop --plan`: per-stage max cost + exact env values (SFT or RL vars) | same | same |
| A6 | Contenders base / `sft-<h12>` / `grpo-<h12>` from sealed manifests; fitness + kill rate num/den/excluded and deltas vs base | `eval/`, `scripts/run_evaluation.py` | `tests/test_eval_runner.py` |
| A7 | Pins resolve for linux x86_64 (torch 2.6.0 / CUDA 12.4); QLoRA seq-2048 ≈ 15 GB on L4 (estimate); smoke ceiling $0.20 | `docs/model-runs/GPU_READINESS.md` | `tests/test_gpu_readiness.py` (pin drift) |
| A8 | Retry only `TRANSIENT_CODES` (timeout, transport_error, invalid_response); 900 s episode wall-clock cap; kill switch `<root>/STOP` (exit 4) | `agents/model.py`, `agents/runner.py`, `scripts/run_loop.py` | `tests/test_episode_runner.py`, `tests/test_run_loop.py` |
| A9 | `GET /loop/status` (whitelisted fields, no paths) + `/system` loop panel | `api/main.py`, `web/src` | `tests/test_run_loop.py`, vitest, tsc, lint, `next build` |
| A10 | Human steps + commands for iteration 1 (SFT) and 2 (GRPO) | `docs/model-runs/RUNBOOK.md` | — |
| A11 | `--algorithm grpo` through Agent B's `train_lora --algorithm grpo --rollouts`; dry-run GRPO end to end | `scripts/run_loop.py` | `test_grpo_dry_run_end_to_end` (runs on this branch after merging main) |

Full suite after merging main (A through A10 + B): 604 passed, 2 skipped. Secret scan: 0 findings.

## Honesty rules kept
- Dry runs use the scripted oracle (reads the answer key) on the synthetic catalog: every stage file says
  `pipeline_evidence_scripted_dry_run`; its adapter is a placeholder file. Real runs refuse a dry-run adapter.
- Real training refuses scripted traces (`train_lora` without `--allow-scripted-traces`).
- The leakage audit runs as its own stage before training and again inside `train_lora`.
- Loop generation runs `--memory off`, so rollout prompts are exact (GRPO refuses memory-enabled rollouts).
- Cold start, step time and memory peak are not measured: `null` / marked estimates.

## Still blocked (exact variables)
Every real stage stops with exit 3 until the human sets, in the env file:
- Inference: `CRUCIBLE_MODAL_TOKEN_ROTATED=1`, `CRUCIBLE_MODAL_BILLING_CONFIRMED=1`, `CRUCIBLE_MODAL_APPROVED_CEILING_USD`.
- SFT: `CRUCIBLE_MODAL_TRAINING_CEILING_USD`, `CRUCIBLE_MODAL_TRAINING_APPROVED_MANIFEST_HASH` (after curate).
- GRPO: `CRUCIBLE_MODAL_RL_CEILING_USD`, `CRUCIBLE_MODAL_RL_APPROVED_ROLLOUTS_HASH` (after plan).
- Plus a Modal payment method and deploy flags (`CRUCIBLE_ENABLE_L4_PROBE` / `_TRAIN` / `_RL`). See the runbook.

## Notes
- Kill rules are episode-level; a rollout attributes them to the terminal turn.
- The inference cost bound is worst case (120 s per call, retries, 900 s episode cap); pass `--seconds-per-call`
  after the first measured run to tighten it.
