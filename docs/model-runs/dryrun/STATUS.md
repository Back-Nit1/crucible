# Training dry run

Status: **planned only** on 2026-11-02. No Modal function was called, no GPU was allocated, no adapter exists, and external
spend is **$0**.

The input was an eight-record curated survivor set from a 16-episode scripted-oracle generation over the committed
audited reference tasks and the real frozen Elastic snapshot. Scripted shoppers read the answer key, so this proves only
the generation → curation → leakage gate → SFT shard → bounded plan plumbing. It is not model training data and none of
the episode outcomes are model-performance measurements.

The plan re-ran the protected/reference leakage audit and recorded audit hash
`1d7534400e6cd9821e2c99888203c5f0e7e9960f374b75495c101dd93d733b91`. The resulting maximum approved cost was `$0.50`,
the plan hash was `59f33b4d8e782e8272aa057f6caa4fa38850b1e0a65d38f4eb8bc1362a3d45b8`, and the content-addressed dataset hash was
`03376bca16bf0c376239b2a5a086c93d8cb506eabf8471e4fb67f7afef3a30f0`.

Reproduction (the first command reads the configured Elastic snapshot but uses no model or paid compute):

```bash
unset VIRTUAL_ENV
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

`--allow-scripted-traces` is deliberately explicit. Omitting it refuses the oracle traces.
