# Runtime / integration status (Agent 1) — branch `feat/operational-world`

Base: `main` = `feat/platform-m1-m3` (fast-forward) + `feat/core-m2-m5` (`merge: integrate platform and deterministic core`).
Tests: `UV_CACHE_DIR=/tmp/crucible-integrated-uv uv run pytest -q` -> see the latest line in the phase log below. Live tests: `pytest -m live` (opt-in).

## Phase log
| Phase | State | Evidence |
|---|---|---|
| 1 merge + packaging | done | 140 passed baseline held; `pyproject.toml` packages the 12 packages |
| 2 contracts | done | `FrozenCatalogProvider`, `get_review_ids`, canonical review ids, provenance (live-verified on 590 products / 14,541 review ids) |
| 3 quote | done | `payments/quote.py` + quote-aware `GuardedPayments`; 15 adversarial tests |
| 4 traces/memory | done | `memory/episodes.py`; live Elastic round trip in a disposable index passed |
| 5 checkpoints | done | `world/store.py` |
| 6 operational generation | **done (live)** | `docs/runs/gen-20261101-p8-t12/` — 96 episodes, 96 traces in Elastic, interrupted at 40 then resumed |
| 7 Modal scheduler | done (remote smoke passed) | `modal_app/world_runner.py`; remote 24-episode run, interrupt at 10 then resume (14), rerun no-op; ~$0.004 total; schedule OFF (needs `CRUCIBLE_ENABLE_SCHEDULE=1`) |
| 8 PayPal + Kernel live | **blocked**: `PAYPAL_SANDBOX_BUYER_EMAIL` and `PAYPAL_SANDBOX_BUYER_PASSWORD` are not in `.env` | `scripts/paypal_live_check.py` ready, exits 3 naming the missing variables; no live approve/capture/duplicate-capture/latency numbers exist |
| 9 API | done | `api/world.py`, `api/readers.py`; 14 contract tests; real-data samples in `docs/api/samples/` |
| 10 deployment | foundation done, nothing deployed | `render.yaml` (free), `docs/DEPLOYMENT.md`, `/health` `/ready` `/config`, JSON access logs, Postman world folder |

## Contracts Agent 2 can consume
- `catalog.providers.base.FrozenCatalogProvider`: `iter_products(category, manifest_hash)`, `get_review_ids(product_id) -> ReviewIds(product_found, ids)`; `SnapshotMismatch`, `IncompleteReviewIds`. `tasks.engine.build_task(..., catalog, manifest_hash, ...)` now takes them (the old `search("")` enumeration is gone). Test fixture: `tests/fixtures/scoring.py::InMemoryCatalog`, `FIXTURE_MANIFEST`.
- `Review.id` is canonical `amazon2023:<parent_asin:asin:user:ts>[:n]`; `Review.source_review_id` is the original key. `catalog.indexing.legacy_to_canonical` migrates v1 citations. `Product` carries `snapshot`, `manifest_hash`, `source_product_id`.
- `payments.quote.Quote`, `ItemPriceQuotes` (frozen training: item price only, labelled), `MockQuotes` (deterministic all-in). `GuardedPayments(backend, catalog, quotes=None, require_all_in=False, clock=...)`; new violations `QuoteStale`, `QuoteChanged`, `QuoteIncomplete`.
- `memory.TraceRecord` v2 (full episode + split/catalog hash/seed/genome/kills/payments); `memory.episodes.RepositoryMemoryProvider(repo)` implements `agents.memory.MemoryProvider` (`record`, `store`, `retrieve`); `TraceRepository.by_generation`.
- `world.store.GenerationStore` (+ `FileBlobStore`/`MemoryBlobStore`), `world.runtime.run_generation / audit_and_curate / build_population`, `world.taskgen.generate_tasks`, `world.scripted.scripted_policy` (ActionPolicy; `agents.model.AdapterPolicy` is a drop-in once Agent 2's `ScriptedModelAdapter` lands on main).
- Scorer fix: `OUT_OF_STOCK` only when the task requires a variant (Amazon data has no stock).

## Findings for Agent 2
- `feat/core-generation` (their orchestrator, `tasks/batch.py`, `agents/model.py`) is **not merged**; it defines a parallel `FrozenTrainingCatalog`. Reconcile onto `FrozenCatalogProvider` when merging.
- `REVIEW_SIGNAL_RECALL` compares `(signal.product_id, rid)` with citations on the *recommended* product, so on a review trap (where the signalled spec-best item must NOT be bought) recall cannot reach 1. Trap episodes score ~0.80.
- Several kill rules are unreachable through the action state machine (K004/K006/K007 are pre-empted by `InvalidActionOrder`); fixtures trigger K001, K002, K003, K008.

## Environment names
`ELASTIC_ENDPOINT` | `ELASTIC_CLOUD_ID`, `ELASTIC_API_KEY`, `PAYPAL_CLIENT_ID/SECRET/ENV`, `PAYPAL_SANDBOX_BUYER_EMAIL/PASSWORD`, `KERNEL_API_KEY`, `MODAL_TOKEN_ID/SECRET`, `PAYMENTS_BACKEND`, `REQUIRE_ALL_IN_QUOTE`. The repo `.env` lives outside this worktree; scripts take `--env-file` and never print values.

## External calls and cost (this branch)
Elastic Serverless only: reads (snapshot enumeration, review ids), ~600 search/embedding calls per 96-episode generation, one disposable-index live test. No PayPal calls, no Modal compute, no paid GPU.

## Reproduce
```
export UV_CACHE_DIR=/tmp/crucible-integrated-uv
uv sync && uv run pytest -q
uv run python -m scripts.run_generation --env-file <path/to/.env> --provider elastic_snapshot --model scripted \
    --payments mock --seed 20261101 --population 8 --tasks 12            # add --interrupt-after 40, rerun to resume
uv run python -m scripts.rehash_manifests --env-file <path/to/.env>      # dry run; --write to refresh manifests
uv run python -m pytest -m live tests/test_memory_live.py                # needs ELASTIC_* in the environment
```
Scripted shoppers read the task reference answer: all reported scores are pipeline evidence, not model performance.

## API contracts for the web app (Agent 2)
`GET /world/generations[/{id}]`, `/world/episodes` (filters: generation_id, agent_id, split, category, killed, kill_rule_id, min/max_fitness; sort: `fitness|episode_id|agent_id|generation_id|category|killed`, `-` prefix = desc; `offset`/`limit<=200`), `/world/episodes/{id}` (ordered `replay`, `kills` with evidence, `score_components`, `genome`), `/world/leaderboard`, `/world/kills`, `/world/kill-rules`, `/models/evaluations`, `/models/checkpoints`, `/payments/ledger` (mock/sandbox only), `POST /agent/run` (`AgentRunResult`; 503 `model_unavailable` until a runner is injected via `create_app(runner=...)`), `/health`, `/ready`, `/config`. Errors are `{"error": {"code", "message"}}`. Samples: `docs/api/samples/*.json`. Postman folder "World, models, ledger".
`/models/*` read Elastic indices `evaluations` and `checkpoints` (documents shaped `{id, ...}`); they are empty until Agent 2's eval/training publishes into them.

## Evidence (this session)
- Merged state: `main` = platform + core + packaging; `feat/operational-world` = 20+ commits on top (`git log --oneline main..`).
- Tests: 209 passed, 4 deselected live tests (`-m live`: memory round trip, frozen catalog vs manifests, PayPal x2 — the Elastic ones pass, the PayPal ones need credentials).
- Operational generation `gen-20261101-p8-t12`: 12 tasks (9 feasible, 3 impossible, 2 review-sensitive), 8 genomes (4 honest, 4 fixtures), 96 episodes, 96 traces in Elastic (interrupted at 40, resumed 56, 0 duplicates), 36 killed (K001 12, K002 18, K003 6, K008 9, K004 21 as co-fire), 3 survivors, 0 hallucinated purchases, 0 budget violations charged (6 attempts blocked at the guard), 21/24 correct no-match on impossible episodes (the other 3 were the hallucinator fixture), 49 grounded SFT records.
- Elastic currently holds 144+ traces (this generation 96 plus two Modal smoke generations of 24 each). `generations`/`kill_rules` documents exist for the local generation only.

## Remaining blockers / risks
1. Sandbox buyer credentials (Phase 8). 2. Modal GPU needs a payment method (training/inference not possible). 3. No model runner for `/agent/run`. 4. Agent 2 branch not merged; see "Findings for Agent 2". 5. Hash of manifests changed with the review-id migration, so any task set generated before it is not valid for the current snapshot. 6. Render not deployed (needs user decision on service creation); the free tier sleeps.
