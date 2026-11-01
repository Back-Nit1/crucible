# Modal inference + resumable LoRA training (Agent 1) — branch `feat/modal-training-runtime`

Base: `origin/main` @ `11fcb1f`. External spend: **$0**. No Modal function was deployed or called, no GPU was allocated, no adapter
exists. Everything below that says "verified" says where.

## Status
| Area | State |
|---|---|
| Qwen inference server hardening + adapter serving (`modal_app/qwen_service.py`, `qwen_inference.py`) | **built**; policy tested offline (fake engine); real engine **verified on CPU with a tiny Qwen2 + a really trained adapter** (adapter changes output, base stays base after load); **never run on Modal/L4** |
| Adapter-pinned client (`agents/qwen_client.py`) | **built**, tested end to end offline (client -> injected transport -> service) |
| Bounded 20-prompt probe (`scripts/qwen_probe.py`) | **built**; **`blocked_not_run`** (artifact: `docs/model-runs/qwen-probe-20261101/probe.{json,md}`); no latency/token/cost/validity numbers exist |
| Training pipeline (dataset, plan, gates, resume, trainer, artifact) | **built**; resume equivalence **proven** offline (stateful fake backend) **and** on the real PEFT backend (tiny Qwen2, bit-identical adapter after interrupt + resume) |
| Modal training job (`modal_app/qwen_training.py`) | **built**; imports and registers `train` offline; **never deployed or run** |
| A trained Qwen-7B adapter | **does not exist**. Nothing in this repo claims one |
| Population re-entry (`training/checkpoints.py`) | **built**, tested (base, adapter, incompatible, scripted, resume compat) |

## Authorization blockers (exact)
Inference/probe (existing): `CRUCIBLE_MODAL_TOKEN_ROTATED=1`, `CRUCIBLE_MODAL_BILLING_CONFIRMED=1`, `CRUCIBLE_MODAL_APPROVED_CEILING_USD=<usd>`
and a payment method on the Modal workspace (L4 functions are refused without one). Ceiling on record: `$0.861948` (45 min L4+2 CPU+32 GiB). Not raised.

Training adds two gates, all required, all set only by the human: `CRUCIBLE_MODAL_TRAINING_CEILING_USD=<usd>` and
`CRUCIBLE_MODAL_TRAINING_APPROVED_MANIFEST_HASH=<training manifest content_hash>` (approval is bound to the exact data). Deploy-time:
`CRUCIBLE_ENABLE_L4_TRAIN=1` (inference: `CRUCIBLE_ENABLE_L4_PROBE=1`); without them the functions have no GPU and fail closed.
`training.gates.authorize_training` also requires the pinned model+revision, `L4`, and `plan.maximum_approved_cost <= ceiling`; the container
re-checks all of it (`training.service.check_request`) including that `budget_seconds x list rate <= ceiling`.

## Contracts (stable; Agent 2 / integrator rely on these)
* **Artifact**: `modal_app/adapter_artifact.ArtifactManifest` (`crucible-adapter-v1`), sealed by `manifest_hash`; `adapter_hash` = hash of all adapter
  files; `checkpoint_id = qwen-lora-<adapter_hash[:12]>`; only exists for a **finished** run (`steps_completed == total_steps`). Fields include run id,
  base model + 40-hex revision, `adapter_path`, file list, `training_manifest_hash`, `dataset_hash`, `data_source_model_version`, `plan_hash`,
  hyperparameters, steps/epochs, checkpoint lineage, per-launch segments, measured `duration_seconds`, `gpu`, `cost_usd`+`cost_basis` (both `null` if unknown), `created_at`.
* **Reference** (`docs/model-runs/<run>/adapter_ref.json`, `training.checkpoints.adapter_reference`): `adapter_ref`
  (`modal-volume://crucible-qwen-adapters/runs/<run>/final@<adapter_sha256>`), `adapter_sha256`, `base_model`, `base_revision`, `training_manifest_hash`, `checkpoint_id`, ...
* **Wire**: `QwenRequest.adapter` is optional `{run_id, adapter_hash, training_manifest_hash}` (identity only, never a path). Absent = base, unchanged on the wire.
  Responses add `adapter_run_id/adapter_hash/training_manifest_hash` only for adapters. Pre-inference refusals are returned as `{"error_code","detail"}` and surface as
  `InferenceError(code)`: `adapter_hash_mismatch`, `training_manifest_mismatch`, `base_model_mismatch`, `adapter_missing`, `adapter_content_mismatch`, `invalid_manifest`,
  `adapter_load_failed`, `input_too_long`, `model_revision_mismatch`, `invalid_request`. There is no path that answers an adapter request from the base model.
* **Selecting a checkpoint for a genome**: `Genome.model_checkpoint` is `qwen-base` or `qwen-lora-<12 hex>`;
  `CheckpointCatalog.from_manifest_files([...]).adapter_for(make_client)` -> `world.runtime.model_policy_factory(adapter_for, ...)`.
  Scripted/unknown labels raise (never become base). Resume compatibility already includes the label (`model_policy_id`), hence the adapter hash prefix.
  `scripts/run_generation.py` is not mine and is **not** wired to this; add `--adapter-manifest` there using `CheckpointCatalog`.

## Training design
`dataset.py` (laptop: manifest/hash/split/PII checks -> content-addressed shard; train targets = assistant tool calls only; `final_answer` is runner-synthesized so excluded;
rendered through the same converter inference uses) -> `gates.py` -> `modal_app/qwen_training.py::train` -> `service.execute` -> `trainer.run_training` (seeded data
schedule, checkpoint cadence, wall-clock budget, `on_durable` = `Volume.commit`) with `resume.CheckpointStore` (temp dir + fsync + atomic rename, per-file SHA-256, corrupt
skipped and recorded, incompatible aborts, never restarts silently, unclosed launches charged wall-clock capped at their allowance) -> `artifacts.finalize_artifact` (atomic `final/`).
`torch_backend.py` is the production numerics (PEFT LoRA r16 on all linear projections, NF4 QLoRA by default, AdamW + cosine, token-level loss, saves adapter + optimizer + scheduler + torch RNG).
Pins: torch 2.6.0, transformers 4.49.0, accelerate 1.4.0, peft 0.14.0, bitsandbytes 0.45.3 (+ the inference pins) in the Modal images only; `pyproject.toml`/`uv.lock` untouched (nothing new is needed by the offline suite).

## Tests (exact)
```
uv run pytest -q                                   # 411 passed, 1 skipped (real-backend test, torch absent), 5 deselected (live)
# real PEFT/Transformers backend on a tiny random Qwen2 + the real pinned Qwen tokenizer (CPU, ~30 s, downloads ~11 MB of public tokenizer files once):
uv run --no-project --with huggingface-hub==0.29.3 python -c "from huggingface_hub import snapshot_download as s; s('Qwen/Qwen2.5-7B-Instruct', revision='a09a35458c702b33eeacc393d103063234e8bc28', allow_patterns=['tokenizer.json','tokenizer_config.json','vocab.json','merges.txt','config.json'], local_dir='<TOKDIR>')"
CRUCIBLE_TEST_QWEN_TOKENIZER_DIR=<TOKDIR> uv run --no-project --with torch==2.6.0 --with transformers==4.49.0 --with accelerate==1.4.0 --with peft==0.14.0 \
  --with safetensors==0.5.3 --with huggingface-hub==0.29.3 --with numpy --with pytest --with pydantic --with jsonschema --with fastapi --with httpx --with pyyaml --with modal \
  python -m pytest -q tests/test_training_torch_backend.py     # 5 passed
uv run python -m scripts.secret_scan --env-file "<real .env>"   # 0 findings
```

## Live run (only after the human sets the variables; do not run otherwise)
```
uv run python -m scripts.train_lora --records docs/runs/<gen>/sft.jsonl --manifest docs/runs/<gen>/training_manifest.json --run-id <id> --max-cost 0.50 --plan-only
export CRUCIBLE_MODAL_TOKEN_ROTATED=1 CRUCIBLE_MODAL_BILLING_CONFIRMED=1 CRUCIBLE_MODAL_APPROVED_CEILING_USD=0.861948
export CRUCIBLE_MODAL_TRAINING_CEILING_USD=<usd> CRUCIBLE_MODAL_TRAINING_APPROVED_MANIFEST_HASH=<content_hash from training_plan.json>
CRUCIBLE_ENABLE_L4_PROBE=1 uv run modal deploy modal_app/qwen_inference.py
uv run python -m scripts.qwen_probe --env-file <.env>                                   # 20 prompts; pass bar is a PROPOSAL (>=90/90/90); exit 0 passed / 1 failed / 3 blocked
CRUCIBLE_ENABLE_L4_TRAIN=1 uv run modal deploy modal_app/qwen_training.py
uv run python -m scripts.train_lora ... --launch --epochs 4 --max-steps 4 --stop-after-steps 2 --env-file <.env>   # smoke, pauses after 2 steps
uv run python -m scripts.train_lora ... --launch --epochs 4 --max-steps 4 --env-file <.env>                         # same run id: resumes, finishes, writes artifact_manifest.json + adapter_ref.json
uv run python -m scripts.inspect_training_artifact docs/model-runs/<id>/artifact_manifest.json
uv run python -m scripts.qwen_probe --adapter-manifest docs/model-runs/<id>/artifact_manifest.json --out docs/model-runs/<id>/probe_adapter   # adapter vs base on the same 20 prompts
uv run modal app stop crucible-qwen-training; uv run modal app stop crucible-qwen-inference
```
`train_lora` refuses scripted-shopper traces (`manifest.model_version` starting `scripted`) unless `--allow-scripted-traces`: they read the answer key, so an adapter
trained on them is pipeline evidence, not a model-quality result (the artifact records `data_source_model_version`).

## Known risks / not verified
1. **Never executed on a GPU or on Modal.** Unverified: bitsandbytes 0.45.3 + torch 2.6.0 on an L4 (CUDA discovery), QLoRA memory/throughput at seq 2048 (expected to fit 24 GB;
   step time unknown, so the wall-clock budget, not a step estimate, is what bounds cost), Modal Volume v2 rename/commit semantics under a hard kill, `Volume.reload()` visibility to the
   inference container, image build time for two 15 GB model layers. peft 0.14.0 + transformers 4.49.0 is verified on CPU only.
2. Cost is an **estimate** (measured seconds x list rates recorded 2026-10-31); Modal billing is the truth. Unknown cost is `null`, never 0.
3. Existing survivor traces (`rc-real-20261102`) are scripted-oracle traces (30 SFT records from 3 survivors); training on them proves the pipeline, not behavior. The evaluation
   workstream reports world.taskgen tasks overlapping protected splits at the product level: audit with their `scripts.audit_split_leakage --training-manifest` before any real training.
4. Training prompt variant is fixed to `grounded-shopper-v1`; genomes use v1-v3 + mutations at inference.
5. The probe is first-turn only; its pass bar is a proposal awaiting confirmation. Metric definitions changed from schema v1 (schema-valid is now measured over structured calls so it
   is not vacuous); thresholds did not.
