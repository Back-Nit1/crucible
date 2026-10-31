# Integration/runtime status — branch `feat/integration-runtime`

Base: `6782e35` (merge of `feat/platform-m1-m3` + `feat/core-m2-m5`); `main` itself had neither merged. Tests: **200 passed, 2 live deselected**.

## Task status (user's list)
| # | Task | Result |
|---|---|---|
| 1 | Package config | Done: `[tool.setuptools.packages.find]` with all 11 packages; `tests/test_packaging.py`. |
| 2 | Enumeration protocol | Done: `SnapshotCatalog.iter_products`; empty query rejected; `TrainingCatalog` adapter. Live: 590 products. |
| 3 | Complete review-id lookup | Done: `review_ids`, `review_count`, paged `get_reviews`. Tested with 25,000 reviews. |
| 4 | 17 id collisions | Done and migrated live. All 17 were identical duplicate rows. 14,541 reviews, 14,541 distinct ids. |
| 5 | EpisodeRecord -> TraceRecord | Done: `memory.adapter` (note: `EpisodeRecord` is in `agents.actions`, not `scoring.schemas`). |
| 6 | Persist full EpisodeRecord | Done: complete JSON in `traces.episode` + split, killed, fitness, seed, catalog hash, ordered calls, provenance. |
| 7 | Elastic `MemoryProvider` | Done: `TraceMemoryProvider(ElasticTraceRepository(es))`. Live-verified retrieval and exclusion. |
| 8 | Atomic checkpoints | Done: `memory.checkpoints.CheckpointStore`. Crash, corruption, concurrency and resume tests. |
| 9 | Quote contract | Done: `payments.quote`, wired into `GuardedPayments` and the API. |
| 10 | Router -> task generation | Done: `catalog.taskgen` + `scripts/generate_tasks.py`; `data/tasks/tasks_v1.json`. |
| 11 | Scripted episode on real data | Done live: success, no kills, fitness 0.97, real product, real cited review id. |
| 12 | Persist + retrieve from Elastic | Done live: round-trip equal; test-split and killed decoys excluded; test-split request got 0. |
| 13 | One in-memory generation | Done live: 40 pairs, 36 scored + 4 unscriptable, interrupted at 15 then resumed 25 with 0 overlap, 36 traces, 0 duplicate ids, 0 kills, 3 survivors, next generation 4. |
| 14 | Kernel-approved capture | **BLOCKED**: `PAYPAL_SANDBOX_BUYER_EMAIL/PASSWORD` unset. |
| 15 | Qwen probe | **BLOCKED**: Modal "Please add a payment method to use L4 GPU functions". $0 spent. |
| 16 | Docs | Done (DECISIONS, README, providers.yaml, ARCHITECTURE, this file). |

## Things agent 2 / the user must decide
1. **`scoring/gate.py` was changed** (one line, commit "fix(scoring): do not fail the gate on stock the source never provides"). Without it every real purchase scored G=0. Revert only if replaced by an equivalent rule.
2. **Task granularity**: tasks use broad dataset categories; `LeakageGuard` rejects 5/48 tasks (test vs train feasible-set overlap). Product-type sub-categories from `attributes.categories` would allow disjoint splits.
3. **Aggregation** in `modal_app/generation_runner.py` is interim: genome fitness = mean of scored episodes; killed if any episode tripped a kill rule.
4. `agents.runner.run_episode` calls `memory.retrieve(...)` and discards the result; memory never influences a policy yet.
5. K004 requires comparing >=2 candidates even for correct no-match answers.

## Reproduce
```
UV_CACHE_DIR=/tmp/crucible-runtime-uv uv run pytest -q
uv run python -m scripts.generate_tasks --env-file .env --per-category 12 --seed 20261101 --out data/tasks/tasks_v1.json
uv run python -m scripts.live_episode --env-file .env          # items 11-12 (throw-away it_ indices, dropped after)
uv run python -m scripts.run_generation --env-file .env --population 4 --tasks 10 --interrupt-after 15   # item 13
uv run python -m scripts.migrate_review_ids --raw-dir <dir with snapshot_*.json> --env-file .env --apply  # already applied
```

## External calls and cost
Elastic Serverless: review-id migration (`_mget` + 14,541 bulk writes + one delete-by-query), task generation and generation runs (paged reads), tens of EIS embedding calls (query-time only). PayPal: none this session. Channel3: none. Hugging Face: none. Modal: one rejected GPU launch ($0). The real `traces` index remains empty (all test traces went to a dropped `it_` prefix).
