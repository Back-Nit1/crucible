# Agent B model-pipeline work summary

Last updated: 2026-11-03. This document summarizes the work completed in the Agent B worktree and distinguishes built
offline machinery from live model results that do not exist.

## Scope

Agent B owned the Qwen inference and training pipeline, generation/training data safety, evaluation harness, model-run
documentation, and model-pipeline handoff. Agent B did not deploy to production or push directly to `main`.

The work began from `origin/main@11fcb1f` and integrated two pre-existing feature histories:

- `origin/feat/modal-training-runtime`: Qwen inference hardening, adapter serving, resumable LoRA training, artifact
  verification, and checkpoint population re-entry.
- `origin/feat/measured-evaluation`: protected tasksets, leakage auditing, frozen evaluation memory, contender manifests,
  resume-safe execution, denominator-aware metrics, WebShop adapter, reports, and idempotent publication.

Agent A subsequently merged the verified Agent B integration into `main` in commit `341d10b` using the handoff target
`ded4e44`.

## Work completed

### Audited generation inputs

`scripts/run_generation.py` now supports:

- `--taskset <directory>` to load the recorded protected and reference files;
- hash verification of both task files;
- a fresh split-leakage audit before generation;
- generation from `reference.jsonl` only; and
- non-zero refusal when the audit fails or too few audited reference tasks exist.

This closes the earlier product-level split leak caused by `world.taskgen`, which computed feasible sets over an entire
category before assigning splits.

### Adapter-pinned generation

`scripts/run_generation.py` also supports `--adapter-manifest`. The sealed artifact is loaded through
`training.checkpoints.CheckpointCatalog`; every genome and request is pinned to the derived
`qwen-lora-<adapter-hash-prefix>` checkpoint. Unknown, scripted, incompatible, or tampered checkpoint identities are
refused. A requested adapter is never silently replaced with the base model.

### Fine-tuned evaluation contenders

`eval.contenders.AdapterReference.from_artifact_manifest` derives the neutral evaluator reference directly from a
sealed training artifact. `scripts/run_evaluation.py` can construct separately pinned base and adapter clients for the
same protected task/seed matrix. The adapter identity is sent on every inference request and verified on every response.

The same adapter selection is wired into the WebShop runner, although WebShop itself has not been installed or run.

### Mandatory pre-training leakage gate

`scripts/train_lora.py` now invokes the shared `scripts.audit_split_leakage` implementation before a launch can reach
authorization or transport. The gate binds:

- the protected task file and recorded hash;
- the reference task file and recorded hash;
- the exact training manifest;
- source task splits; and
- the frozen category manifests.

A failed audit refuses both planning and launch. Memory eligibility may be explicitly `not_run` for a training-only
audit; training-source leakage may not be skipped.

### Published document contract

Evaluation documents now expose the fields consumed by the Model dashboard:

- `contender`, `status`, `seeds`, and checkpoint identity;
- `pass_at_k`, latency, cost per task, and seed variance; and
- metric `numerator`, `denominator`, `excluded`, and `value`.

Unmeasured values remain null. Checkpoint documents expose the dashboard's manifest and catalog fields without inventing
unknown values. Contract tests validate a published sample.

### Training-data PII handling

The audited dry run exposed a false positive: namespaced Amazon review identifiers can contain 13–19 consecutive digits.
The training-data filter now distinguishes those identifiers from naked card-shaped values. Naked candidate card
numbers must pass a Luhn checksum before being treated as payment-card data; email and telephone detection is unchanged.

### Serving analysis

[`docs/model-runs/SERVING_OPTIONS.md`](../model-runs/SERVING_OPTIONS.md) documents:

- L4 scale-to-zero, scheduled warm, continuously warm, and typed degraded modes;
- current Modal list-rate arithmetic for one L4, two CPU cores, and 32 GiB memory;
- the fact that this model's cold-start time is not measured;
- proposed per-IP and per-session request caps;
- Workspace budget and net-spend-limit requirements; and
- the existing typed `model_unavailable` behavior.

No serving option has been selected, so Agent B did not deploy one.

## Offline dry run

The no-spend pipeline proof used four audited reference tasks and the real frozen Elastic snapshot with a scripted-oracle
shopper:

| Item | Recorded value |
|---|---:|
| Episodes executed | 16 |
| Curated SFT records | 8 |
| Paid/model calls | 0 |
| Maximum plan | $0.50 |
| External spend | $0 |
| Leakage audit | Passed |
| Plan status | Planned only |
| GPU allocated | No |
| Adapter produced | No |

The plan hash is `59f33b4d8e782e8272aa057f6caa4fa38850b1e0a65d38f4eb8bc1362a3d45b8`; the dataset hash is
`03376bca16bf0c376239b2a5a086c93d8cb506eabf8471e4fb67f7afef3a30f0`. Evidence is in
[`docs/model-runs/dryrun/`](../model-runs/dryrun/).

These traces are pipeline evidence only. The scripted shopper reads the reference answer, so the outcomes are not model
performance and are not eligible for real training or evaluation claims.

## Verification

Before the Agent B handoff:

```text
463 passed, 1 skipped, 5 live tests deselected
split-leakage audit: passed
secret scan: 0 findings
```

After synchronizing with Agent A's release work on 2026-11-03:

```text
548 passed, 1 skipped, 6 live tests deselected
```

The skipped test is the optional real Torch/PEFT backend test because the normal offline environment does not install
the large training stack. Live-provider tests are deselected from the default suite.

## Live-stage status

No live Qwen stage ran. At the final checks, none of these human-controlled variables had a configured value:

```text
CRUCIBLE_MODAL_TOKEN_ROTATED
CRUCIBLE_MODAL_BILLING_CONFIRMED
CRUCIBLE_MODAL_APPROVED_CEILING_USD
CRUCIBLE_MODAL_TRAINING_CEILING_USD
CRUCIBLE_MODAL_TRAINING_APPROVED_MANIFEST_HASH
```

`CRUCIBLE_ENABLE_SCHEDULE` was also not set.

Consequently:

- no Modal app was deployed;
- no GPU was allocated;
- the 20-prompt Qwen probe was not run;
- no base-Qwen generation exists;
- no real-model memory pool exists;
- no LoRA adapter exists;
- no protected evaluation episode exists;
- no evaluation or checkpoint result was published; and
- actual Modal/model spend remains $0.

The committed evaluation directory contains a planned manifest, protected/reference taskset, audit, exclusions, and an
explicit `blocked_not_run` WebShop record. It does not contain a model-results report.

## Phase 3 assessment

The requested results-hardening phase had an explicit precondition: Stage E must either publish evaluation records or a
stage must fail and require a truthful failure report. Neither condition occurred. Stage E remains `BLOCKED`, not
`FAILED`, because inference authorization, real model traces, a memory pool, and an adapter are absent.

Agent B therefore did not create `RESULTS.md`, fabricate before/after metrics, claim byte-for-byte regeneration of
nonexistent artifacts, deploy a serving option, or perform a live `/agent/runs` inference call.

## Reproduction commands

```bash
unset VIRTUAL_ENV
uv sync
uv run pytest -q
uv run python -m scripts.secret_scan --env-file <ENV_FILE>

uv run python -m scripts.audit_split_leakage \
  --protected docs/evaluations/taskset-20261110/protected.jsonl \
  --reference docs/evaluations/taskset-20261110/reference.jsonl \
  --allow-not-run memory_eligibility \
  --allow-not-run training_source_leakage

# Scripted-oracle pipeline proof; not a model-performance run.
uv run python -m scripts.run_generation --env-file <ENV_FILE> \
  --provider elastic_snapshot --model scripted --memory off --payments mock \
  --seed 20261102 --population 4 --tasks 4 --no-fixtures \
  --generation-id dryrun-audited-scripted \
  --taskset docs/evaluations/taskset-20261110 --traces memory \
  --checkpoint-dir /tmp/crucible-dryrun-checkpoints \
  --out-dir /tmp/crucible-dryrun

uv run python -m scripts.train_lora \
  --records /tmp/crucible-dryrun/dryrun-audited-scripted/sft.jsonl \
  --manifest /tmp/crucible-dryrun/dryrun-audited-scripted/training_manifest.json \
  --taskset docs/evaluations/taskset-20261110 \
  --run-id dryrun --max-cost 0.50 --plan-only --allow-scripted-traces
```

## Key commits

| Commit | Purpose |
|---|---|
| `7d251b4` | Audited taskset generation and adapter pinning |
| `964f152` | Fine-tuned evaluation serving |
| `5c54f2a` | Mandatory pre-training leakage audit |
| `bbd4fb1` | Model-dashboard publication contract |
| `ed7a8fb` | Serving options and list-rate scenarios |
| `0bad6bd` | Namespaced catalog-ID PII fix |
| `c6e21a2` | Audited no-spend training dry run |
| `ded4e44` | Verified Agent B handoff merged by Agent A |

The operational handoff remains [`docs/handoffs/model-pipeline-status.md`](model-pipeline-status.md).
