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
| 7 Modal scheduler | pending | |
| 8 PayPal + Kernel live | blocked: no sandbox buyer credentials | |
| 9 API | pending | |
| 10 deployment | pending | |

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
