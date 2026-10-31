# Core status handoff

Branch: `feat/core-generation` (based on audited platform+core merge `6782e35`)

## 2026-10-31 generation integration update

Implemented after the platform/core integration:

- `FrozenTrainingCatalog` requires an explicit frozen marker, snapshot ID, SHA-256
  manifest hash, deterministic category enumeration, complete product enumeration,
  and complete product-scoped review-ID lookup.
- Seeded batch generation produces a configured 70–80% feasible / 20–30%
  impossible mix. It never adds size or stock requirements to the Amazon snapshot.
  Uncheckable constraints retain unknown feasibility and cannot enter a generation.
- Review traps accept only pre-verified semantic signals whose supporting IDs pass
  the complete product-scoped lookup. Ratings and retrieval rank are never used to
  invent a claim.
- `ModelAdapter` is a vendor-neutral structured-tool-call boundary. The stateless
  `ScriptedModelAdapter` is indexed by persisted history for deterministic resume.
- `world.orchestrator.run_generation` wires the frozen provider, model adapter,
  episode runner, deterministic scorer, kill registry, memory protocol, and
  `GuardedPayments(MockPayments(auto_approve=True))`. Sandbox payments cannot be
  injected into this function.
- Resume requires exactly one persisted episode per completed checkpoint key and
  schedules only missing genome/task pairs.
- Completed generations produce a summary, checkpoint, evaluation JSON/Markdown,
  curated SFT records, and a versioned training manifest. No training occurs.
- `TraceRepositoryMemoryProvider` maps full episode JSON and raw task text to the
  integrated platform memory contract while blocking test/killed/below-threshold
  records.
- `ConfiguredJudgeAdapter` is versioned, input-hashed, cache-keyed, cached, and
  fail-closed. It constructs no network or paid-model client.

Verification on the integrated tree:

- Untouched merged baseline: `140 passed, 2 deselected, 1 warning`.
- Final generation phase gate: `156 passed, 2 deselected, 1 warning`.
- The warning is the existing Starlette/httpx deprecation. Live tests remain
  intentionally deselected.

### Seeded contract-fixture generation metrics

These values are from an explicitly synthetic, in-memory contract fixture, not the
real Elastic snapshot and not a model-quality claim.

| Field | Measured value |
|---|---:|
| Seed / genomes / tasks / episodes | `9 / 2 / 10 / 20` |
| Feasible / impossible / review-trap tasks | `7 / 3 / 1` |
| Survivors | `2` |
| Kills / wrong refusals / hallucinations | `0 / 0 / 0` |
| Success / hard constraints / correct refusal | `1 / 1 / 1` |
| Review grounding / review-trap accuracy | `1 / 1` |
| Persona-relevant review recall | `0.9` |
| pass@1 / budget violation rate | `1 / 0` |
| Mean fixture latency / cost | `0 ms / 0` |
| Mock captures | `14` |
| Grounded SFT records / deterministic duplicates removed | `17 / 3` |
| Training manifest content hash | `329c7ba2e731568fa8402fc450c9f66d7cca9723d07a2c046cc5904060a4c875` |

### Platform changes still required

The integrated `ElasticCatalogProvider` currently exposes capped `search()` and
`get_reviews()` only. A real-snapshot generation is therefore deliberately blocked.
Agent 1 must add, directly or through a training-only adapter:

1. `snapshot_id: str`, a stable identifier for the exact indexed snapshot.
2. `manifest_hash: str`, a 64-character hash covering every included category
   manifest (or a provider per single-category manifest).
3. `is_frozen_training_provider = True` only for the pinned training snapshot.
4. `categories() -> tuple[str, ...]` in stable order.
5. `enumerate_products(category) -> tuple[Product, ...]` using complete bounded
   pagination (`search_after` or equivalent), not the current default `size=10`.
6. `complete_review_ids(product_id) -> frozenset[str]`, scoped to the product and
   complete despite the source review-ID collisions. It must not use semantic
   retrieval or a top-k limit.
7. Add `tasks`, `agents`, `scoring`, `world`, `training`, and `eval` to the shared
   packaging list in `pyproject.toml`.

The four committed real snapshot manifests are represented by manifest-only task
cases (590 built products, 14,541 built reviews); no raw dataset is committed. The
real generation cannot run until the six provider operations above exist. Because
that real generation is not green, the WebShop integration intentionally remains
the documented `WebShopNotConfigured` executable stub.

Last pre-integration core commit: `858aa8e fix(agents): trace rejected budget attempts`.

## Verification

- Untouched baseline: `29 passed, 1 warning` after `uv` downloaded only dependencies already in `uv.lock`. The first sandboxed attempt failed DNS resolution; the approved network retry succeeded.
- Latest full phase gate before documentation: `56 passed, 1 warning`.
- Warning: Starlette reports that its `httpx` TestClient compatibility path is deprecated. Fixing it requires a shared dependency change and is outside this branch's ownership.
- All core tests use explicitly synthetic, test-only in-memory products and reviews. No paid API or external model was called.

## Phase status

| Phase | Status | Available contracts / remaining work |
|---|---|---|
| 1. Core models | Complete | Strict task, constraint evidence, review signal, action, tool-call, episode, genome, generation, checkpoint, scoring, payment-event, and kill-decision models. |
| 2. Task engine | Substantial | Deterministic filtering, unknown-feasibility exclusion, explicit value formula, impossible-task closest pick, seeded rendering/splits, leakage guard, manifest hash, and verified review traps. A configurable batch mix targeting feasible/impossible ratios remains. |
| 3. Action space | Complete for in-memory execution | All nine typed actions, deterministic ordering violations, product/review grounding, comparison requirements, and guarded mock checkout. |
| 4. Scoring | Complete deterministic core | Hard gate, 12 explicit Q components, capped efficiency, correct impossible-task handling, and fixed-judge/cache protocol. Semantic entailment still requires a fixed external judge implementation. |
| 5. Kill rules | Complete initial registry | `K001` through `K008`, stable versions, dates, enabled flags, evidence, and adversarial tests. Rejected over-budget attempts are traced and immediately killed. |
| 6. Episode runner | Complete model-agnostic core | Bounded action policy, retries, tool/token/cost limits, complete ordered records, mock capture, correct no-match, malformed action, model failure, limit, and instant-kill termination. There is no production model adapter yet. |
| 7. Evolution | Complete algorithms | Seeded population, stable genome hashes, tournament selection, bottom-quartile culling, survivor elitism, bounded mutation, lineage, stable checkpoints, and duplicate-free resume planning. An external scheduled generation orchestrator remains. |
| 8. Loophole Hunter | Complete proposal workflow | Requested deterministic detectors produce proposed rules only; explicit confirmation supplies version, reviewer, and reproducing test. Batch review-rating adapters can make positive-only detection stronger. |
| 9. Memory contract | Complete consumer contract | `agents.memory.MemoryProvider` plus leakage-safe in-memory reference implementation. No files under Agent 1's `memory/` ownership were changed. |
| 10. Training curation | Complete | Survivor/grounding/review/split filters, versioned tool-call SFT, deterministic normalized dedupe, and stable manifest hashing. No training is performed. |
| 11. Evaluation | Complete core metrics | Required metrics, numerator/denominator/exclusions, empty denominators, seed variance, JSON/Markdown, and contender placeholders. WebShop is explicitly a protocol stub. |
| 12. Documentation | Complete on this branch | This handoff and `docs/spikes/core-engine.md`; shared README/architecture files were not edited. |

## Contracts Agent 1 must implement or integrate

1. **Packaging:** add `tasks`, `agents`, `scoring`, `world`, `training`, and `eval` packages to the shared `pyproject.toml` package configuration. This branch intentionally did not edit that owned file.
2. **Catalog enumeration:** `tasks.engine.build_task` calls `CatalogProvider.search("", {"category": category})` to enumerate the frozen category deterministically. The production provider must define that behavior, or the shared protocol should gain an explicit snapshot iterator.
3. **Review-ID validation:** scoring and curation call `get_reviews(product_id, limit=10_000)` and require the complete product-scoped ID set. If an external provider caps results, add a complete review-ID lookup contract; silent truncation would create false fabrication kills.
4. **Catalog provenance:** every product must retain `source` and `as_of`. Variant inventory may be marked checkable only when the source actually provides it. Amazon Reviews 2023 stock/size tasks must use `ConstraintEvidence(checkable=False, ...)`, which excludes them from deterministic training without labeling them impossible.
5. **External memory:** implement `agents.memory.MemoryProvider`. Never store or return test traces, killed traces, or traces below the request's threshold; preserve the entire source `EpisodeRecord` and deterministic tie order.
6. **Trace storage:** Elastic serialization can use `EpisodeRecord.model_dump(mode="json")`. Preserve ordered calls, arguments, result references/summary, timestamp, error code, kill rule/version/evidence, catalog hash, and seed.
7. **Payments:** the current public `GuardedPayments` + idempotent backend contract is sufficient for mock execution. A production adapter must preserve capture IDs and idempotency. If taxes/shipping make `Product.price` different from all-in total, a quote/re-price contract is required before deterministic budget scoring; do not silently treat list price as all-in.
8. **Fixed judge:** implement `scoring.judge.Judge` only for semantic checks that catalog attributes cannot decide. Pin prompt/version, hash exact input, cache by the supplied key, and fail closed on malformed output.
9. **Generation storage/orchestration:** persist `GenerationCheckpoint` atomically and schedule only `remaining_episode_keys()` on resume. Do not duplicate a completed genome/task pair.

## Assumptions and blockers

- The frozen provider returns deterministic result ordering and can enumerate a category.
- Fixture variant counts are test-only facts. They must never be presented as Amazon inventory.
- Current deterministic total equals catalog price; tax/shipping quote support is unresolved for providers where that is false.
- Claim-text entailment, real Amazon review-signal extraction, external memory/Elastic, model inference, Modal scheduling, and WebShop execution are not implemented here.
- No dependency was added. The existing deprecation warning requires an owner decision in `pyproject.toml`/`uv.lock`.
- Configurable feasible/impossible batch-ratio generation and a production end-to-end generation scheduler remain the next core work.

## Suggested shared documentation changes

- README: replace “everything else pending” with the phase table above after integration; state clearly that core tests use synthetic fixtures and real catalog adapters remain separate.
- Architecture: add `agents.actions`/`state`/`runner`, `tasks.engine`, `scoring.quality`/`judge`, `world.evolution`/`loophole_hunter`, `training.curation`, and `eval.harness` to the module view.
- Decisions: record that uncheckable hard constraints have an explicit **unknown feasibility** state and cannot become training examples or impossible-task labels.

## Next phase

Integrate a frozen catalog provider with deterministic category enumeration and complete review-ID lookup, then run a one-generation batch through the episode runner and checkpoint store. Do not enable real payment capture in unit or bulk world runs.
