# Model pipeline integration status

Updated 2026-11-02 23:59 EST. Branch: `feat/model-pipeline`. Base: `origin/main@11fcb1f`.

READY-TO-MERGE ded4e44

## Offline integration

**DONE**

- Merged both existing histories with merge commits: `origin/feat/modal-training-runtime` and
  `origin/feat/measured-evaluation`.
- `scripts.run_generation` accepts a sealed `--adapter-manifest`, maps it through `CheckpointCatalog`, pins every genome
  and request to the adapter checkpoint, and never substitutes base. `--taskset` reloads and re-audits the protected and
  reference files, then consumes only `reference.jsonl`; a failed or incomplete audit exits non-zero.
- `AdapterReference.from_artifact_manifest` derives the evaluation identity from a sealed trainer artifact.
  `scripts.run_evaluation` now serves base and fine-tuned contenders through separately pinned clients, including the
  WebShop adapter path; there is no adapter-to-base fallback.
- `scripts.train_lora` runs the shared `scripts.audit_split_leakage` implementation against the taskset's recorded file
  hashes and the exact training manifest before building or launching. A failed audit reaches neither authorization nor
  transport.
- Evaluation and checkpoint documents match the Model dashboard fields. Every rendered metric retains
  numerator/denominator/excluded/value; unmeasured latency, cost, and variance stay null.
- `docs/model-runs/SERVING_OPTIONS.md` records scale-to-zero/warm/degraded choices, current official Modal list-rate
  arithmetic, unmeasured cold-start status, proposed IP/session caps, and the required account-side hard cap. The user
  has not selected an option.
- Offline scripted dry run completed over four committed audited reference tasks and the real frozen Elastic snapshot:
  16 episodes, 8 curated records, 0 paid/model calls. This is oracle pipeline evidence, not model performance. Plan:
  `docs/model-runs/dryrun/training_plan.json`; status: `docs/model-runs/dryrun/STATUS.md`.
- The dry run exposed and fixed a PII-filter false positive: namespaced numeric Amazon review IDs are allowed, while
  naked 13–19 digit strings still need a valid Luhn checksum to be classified as payment-card data. Email and phone
  checks are unchanged.

## Verification

```text
uv run pytest -q
463 passed, 1 skipped, 5 deselected

uv run python -m scripts.audit_split_leakage ... --training-manifest <dryrun manifest> \
  --allow-not-run memory_eligibility
passed=true; product/review/category/training/catalog checks pass; memory eligibility explicitly not_run

uv run python -m scripts.secret_scan --env-file <real .env>
scanned 353 tracked files, 0 findings
```

The one skipped test is the optional real Torch/PEFT backend test because those large dependencies are not installed in
the normal offline environment. The five deselected tests are live-provider tests. The combined offline suite is green.

## Live stages and blockers

Actual external spend: **$0**. Modal deployments: **none**. GPU allocations: **none**. Qwen probe/model generations:
**none**. Adapter: **does not exist**. Measured model evaluation: **does not exist**.

At 2026-11-02 23:53 EST the env-file name-only check returned zero configured values for all five variables:

```text
CRUCIBLE_MODAL_TOKEN_ROTATED=0
CRUCIBLE_MODAL_BILLING_CONFIRMED=0
CRUCIBLE_MODAL_APPROVED_CEILING_USD=0
CRUCIBLE_MODAL_TRAINING_CEILING_USD=0
CRUCIBLE_MODAL_TRAINING_APPROVED_MANIFEST_HASH=0
```

- Stage A — **BLOCKED(missing all three base Modal authorization variables; payment method not verified)**. The proposed
  90/90/90 probe bar still needs human confirmation. No probe metric exists.
- Stage B — **BLOCKED(Stage A not passed and base authorization missing)**. No base or base+memory model trace exists.
- Stage C — **BLOCKED(no real MODEL traces because Stage B has not run)**. Scripted traces are excluded from real
  curation and memory.
- Stage D — **BLOCKED(no approved real training manifest; both training authorization variables missing)**.
- Stage E — **BLOCKED(no deployed inference, real memory pool, or trained adapter)**. The 47-task × 3-seed manifest and
  resume-safe machinery exist, but no episode is measured or published.
- Stage F — **BLOCKED(WebShop clone, Python 3.8 environment, data, Lucene index, and JDK 11 absent)**. Time spent on live
  WebShop setup this session: 0 hours; status remains `blocked_not_run`.
- Stage G — no live stage ran, so there is no Modal billing/run metadata to append. Actual spend remains $0.

## Reproduction

```bash
unset VIRTUAL_ENV
uv sync
uv run pytest -q
uv run python -m scripts.secret_scan --env-file <ENV_FILE>

uv run python -m scripts.audit_split_leakage \
  --protected docs/evaluations/taskset-20261110/protected.jsonl \
  --reference docs/evaluations/taskset-20261110/reference.jsonl \
  --allow-not-run memory_eligibility --allow-not-run training_source_leakage

# no-spend oracle pipeline proof; never report its outcomes as model quality
uv run python -m scripts.run_generation --env-file <ENV_FILE> --provider elastic_snapshot --model scripted \
  --memory off --payments mock --seed 20261102 --population 4 --tasks 4 --no-fixtures \
  --generation-id dryrun-audited-scripted --taskset docs/evaluations/taskset-20261110 --traces memory \
  --checkpoint-dir /tmp/crucible-dryrun-checkpoints --out-dir /tmp/crucible-dryrun
uv run python -m scripts.train_lora \
  --records /tmp/crucible-dryrun/dryrun-audited-scripted/sft.jsonl \
  --manifest /tmp/crucible-dryrun/dryrun-audited-scripted/training_manifest.json \
  --taskset docs/evaluations/taskset-20261110 --run-id dryrun --max-cost 0.50 \
  --plan-only --allow-scripted-traces
```

Do not run any Phase 2 command until the exact stage gates are present and the approved ceiling covers that stage's
maximum plan. The inference/probe ceiling on record remains `$0.861948`; this branch does not raise it.
