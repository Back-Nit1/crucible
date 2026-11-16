# P1 model and harness handoff — 2026-11-12

## Objective and authorization

The user asked to finish the P1 model work in `outline.md`: repair the evaluation harness, audit existing results, run the model pipelines, obtain real model results, and investigate repeated Modal container shutdowns. P0 shipping and P2 hardening were outside this session's focus.

The user explicitly approved **$5** after being asked about a cumulative Modal ceiling. `.env` was updated to `CRUCIBLE_MODAL_APPROVED_CEILING_USD=5`. Treat this as cumulative, not $5 of fresh spending. Never print credentials. Modal CLI needs `MODAL_TOKEN_ID` and `MODAL_TOKEN_SECRET` loaded from `.env` through `scripts._env.load`; default CLI environment reported no token.

P1 is **incomplete**. No successful new model evaluation or finalized adapter was established here.

## Immediate state and blockers

1. A bounded four-episode v7/7B pilot was deployed to `crucible-qwen-inference`, app ID `ap-mX1cEbkhN2ojPGjg6L8taD`, evaluation ID `p1-v7-7b-20261112`.
2. At handoff creation, `/tmp/crucible-p1-run.log` ends with `BLOCKED: inference warm-up failed (InferenceError)` / `No episode was consumed.` Determine the underlying error before another launch; this generic message does not identify its cause.
3. During startup, Modal reported L4 capacity waits and additional image builds. A training task appeared although this session never launched training. Its caller is unknown; concurrent activity is suspected, not proven.
4. Automatic approval review rejected stopping the inference app because it might be shared and stopping could disrupt another process. Do not retry or indirectly stop it without user approval or sufficient new evidence. The last user-facing question requested approval to stop this exact app; no answer was received before this handoff request.
5. The watchdog wrapper PID 21745 was terminated using SIGTERM to disable its scheduled stop and cleanup after that rejection. Evaluation child PID 21910 was deliberately left untouched. These are historical PIDs: verify current processes before acting. **There is no active cleanup/watchdog guarantee. App stop was never confirmed.**
6. Working-tree status changed substantially between the last work and this handoff, suggesting other work landed or modified files. Inspect current git history/diffs before editing. Preserve other work; no commits were made by this session.

## Budget evidence

Read-only Modal billing queries found:

- Nov 1–10 inference: `$3.40105672`.
- Recent hourly inference: `$0.18984031`.
- Recent training: `$0.22679030`.
- Conservative combined baseline used for the pilot: `$3.81768733`.

Billing can lag, and unknown concurrent activity can consume more. Refresh billing and identify running work before spending. Reports: `/tmp/crucible-p1-billing.json`; the attempted all-month hourly report failed, while `--start 2026-11-11 -r h --json` worked. Do not count all-month daily and overlapping hourly intervals twice.

## Findings and reproducible audits

- Base evaluation `checkpoints/evaluations/eval-20261110-base`: 86 records; 53 malformed action, 27 model failure, 6 instant kill; zero successes. Incomplete, not a completed result.
- `pilot-v6-state-tools`: 12 records; 6 model failure, 6 instant kill; zero successes. Read before repeating a paid pilot.
- All six instant kills included hallucinated product `none` and insufficient research. Empty filtered searches followed by refusal were converted into a fake closest-product ID. These were not budget-violation kills.
- All 75 protected/reference tasks were checked against the frozen catalog. Nine budgets fall below every category product price; all nine are correctly marked impossible. Preserve these refusal tasks; protected data was not edited.
- Audit commands: `.venv/bin/python -m scripts.audit_p1_results` and `.venv/bin/python -m scripts.audit_p1_budgets` (the latter loads `.env` and reads Elastic).
- Outputs: `docs/evaluations/p1-saved-results-audit.json`, `docs/evaluations/p1-budget-audit.json`.

## Changes made in this session

Some files already contained substantial uncommitted work when this session began. Attribute only these specific additions to this session:

- `agents/model.py`: retain raw model response alongside SHA-256 in successful metadata and malformed-attempt audit; disallow offering refusal after an empty search with no discovered product; narrow offered product-ID schemas to the discovered/opened/reviewed/ready sets.
- `agents/prompts.py`: instruct broader search when filters return nothing so refusal can cite a real closest alternative. Version advanced v6 -> v7, then **v8** for product-ID restrictions added after the pilot launched.
- `scripts/run_evaluation.py`: default new plans to one seed instead of three identical greedy seeds. Existing manifests remain unchanged.
- `modal_app/qwen_service.py`: exact-token context windowing removes oldest complete assistant/tool pairs while retaining system/buyer/latest exchange. Oversized irreducible prompts still fail closed. This needs live validation and training-format review; it is not evidence of improved model quality.
- `modal_app/qwen_training.py`: check training request pin/approval before loading GPU weights, avoiding waste on an invalid request.
- `modal_app/qwen_inference.py`: initialize engine/service before startup; tolerate missing engine during cleanup; remove an unverified categorical claim that cancellation cannot kill the container.
- Tests: adjusted the prior hash-only expectation to assert raw-response retention; checked empty-search refusal suppression and offered product IDs; added `tests/test_p1_context_window.py` for preserving buyer/latest paired exchange without mutating requests.
- Added audits, `docs/evaluations/P1-20261112.md`, and P1 progress notes/checkmarks in `outline.md`.

The v7 pilot did **not** include the later v8 product-ID restriction or final startup-cleanup edit. Use a new evaluation manifest for v8, and verify current files because other work may have changed them since.

## Container investigation

Historical `DECISIONS.md` entries contain competing explanations: some shutdowns coincided with client cancellation, but the 03:58 shutdown remains unexplained. Current source already had async vLLM, `@modal.concurrent`, durable spawn transport without client cancellation, a 900-second server request timeout, and a 960-second client timeout. Those were pre-existing work, not fixes authored here.

The pilot selected 7B, min_containers=1, four workers, four episodes, long warm-up, and a 30-minute stop guard. That guard was later disabled following the app-stop rejection. No engine lifecycle stability was verified by this pilot. Startup logs showed capacity waits and dependency/model image builds, not enough evidence to diagnose every previous shutdown. Do not claim the decontainerization problem fixed.

## Training discovery and exact resume requirements

Training logs were read from `crucible-qwen-training` (`ap-LZ7HK7tO0T0t2tECdNuc5A`). They included `GateError: unpinned_model`, then a later paused run. The exception cannot conclusively be assigned to smoke3 from those logs alone. Full local log: `/tmp/crucible-p1-training.log`.

The Modal volume `crucible-qwen-adapters` contains **smoke4-20261111**, omitted from the outline. It is paused at **step 1/2**, with a saved checkpoint, not a finalized adapter.

Exact identity:

- Model: `Qwen/Qwen2.5-7B-Instruct`.
- Revision: `a09a35458c702b33eeacc393d103063234e8bc28`.
- Training manifest: `2d630a4a88fb8b278c09626925c93e77fda931201036317a70650113fa6c9ede`.
- Dataset: `98e4f7c1f80a218b9ddb60124bc23c5ff0054867c51e412f828b6c5a58a6ef16`.
- Plan: `9b976d309d742bc187d8a1b98e6f2ecee59dd3ee4d20a3acca9bd84269d3fb35`.
- Original run ceiling: `$0.50`; original budget_seconds 1566; max_steps=4, actual total_steps=2, 13 examples.
- Backend signature: torch 2.13.0 / transformers 5.19.0 / peft 0.21.2 / accelerate 1.15.0 / bitsandbytes 0.50.2.

Original `identity.json`, `ledger.json`, and `dataset.jsonl` were downloaded to `checkpoints/p1-smoke4-resume/`. `training.shard.parse_shard` validated the original dataset and manifest hashes and counted 13 examples.

Regenerating from `checkpoints/loop/dry-1/generation/dry-1-gen/sft.jsonl` and its manifest with today's prompts produced a **different dataset hash** (`44b3d62599917cf0436afc0711b1af225ccbb4375c37f31fb9c47271c5e87759`). Do not use that regenerated shard to resume the saved checkpoint. `docs/model-runs/smoke4-20261111/training_plan.json` records both and warns about this.

A user-input request proposed resuming smoke4 with a `$0.50` training-run ceiling inside the cumulative `$5`, bound to the manifest above. No approval response was received. `outline.md` explicitly asks for training ceiling plus manifest approval. This session did not launch training.

## Validation

- Full suite before the final product-ID/startup-cleanup changes: **670 passed, 3 skipped, 6 deselected**, 23.11s.
- Subsequent targeted agent/client/eval tests: 25 passed.
- Final agent adapter/context tests: 13 passed.
- Training-module/context tests: 6 passed.
- No frontend changes or frontend validation performed here.
- `.venv/bin/ruff` was absent; lint attempt could not run.

## Suggested continuation

1. Read this handoff, `outline.md`, the current git diffs/history, and `docs/evaluations/P1-20261112.md`.
2. Reconcile current Modal activity and the unanswered app-stop approval. Verify the pilot process, app deployment, billing, and any artifacts. Never assume historical PIDs or automatic cleanup remain active.
3. Diagnose the warm-up error from server logs and client error metadata. Confirm the server model/revision matches the intended client before submitting paid episodes.
4. Coordinate one model pin across inference/training; this session chose 7B. Do not overwrite a shared deployment while another caller is active.
5. Validate v8 harness in a new small pilot, then complete a single-seed 47-task base evaluation if budget permits. Preserve incomplete historical runs and honest denominators.
6. Obtain the pending exact training approval; resume using the original shard and identity if appropriate, or make a new explicit plan. Respect the combined cumulative budget, including other callers.
7. Only after a sealed adapter exists: evaluate base versus adapter on the protected taskset, publish real artifacts with `scripts.publish_models`, and update README results.
8. Update outline/work log with verified outcomes. Leave unmeasured results marked Not run. P2 hardening can follow the user's requested P1 work.

Temporary pilot wrapper: `/tmp/crucible_p1_run.py` (historical, guard disabled; do not blindly rerun). Pilot log: `/tmp/crucible-p1-run.log`. Supporting logs and downloaded artifacts may outlive this session but should be checked before relying on them.
