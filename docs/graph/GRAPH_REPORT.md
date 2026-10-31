# Graph Report - Crucible-runtime  (2026-10-31)

## Corpus Check
- 137 files · ~162,591 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 5 file(s) not represented in the graph (top: (none) 3, .example 1, .lock 1)

## Summary
- 1344 nodes · 4087 edges · 69 communities (48 shown, 21 thin omitted)
- Extraction: 87% EXTRACTED · 13% INFERRED · 0% AMBIGUOUS · INFERRED: 537 edges (avg confidence: 0.93)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `036dc806`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- TaskSpec
- TaskSplit
- runner.py
- run_generation
- qwen_toolcalls.py
- harness.py
- guards.py
- ElasticCatalogProvider
- SandboxPayments
- hashlib
- MockPayments
- Product
- ProviderRouter
- sources/snapshot.py
- Communities (26 total, 10 thin omitted)
- pytest
- test_payments_quote.py
- create_app
- Elastic
- test_kernel_approver.py
- main.py
- decimal
- indexing.py
- Channel3Provider
- build_snapshot.py
- json
- Build Spec: Crucible — an evolutionary RL world that trains open models to shop on PayPal
- build_task
- build
- test_catalog_router.py
- PaymentsBackend
- engine.py
- test_api_endpoints.py
- tasks/schemas.py
- test_catalog_enumeration.py
- generate_tasks
- migrate_review_ids.py
- providers/elastic.py
- TrainingCatalog
- Decisions
- Architecture
- Deterministic core engine
- README.md
- LeakageGuard
- 8. Component build specs
- SnapshotCatalog
- contenders.py
- 6. Architecture (mapped out)
- FakePayPal
- 10. Product surface and design direction
- HardConstraints
- Snap
- Platform status (agent 1) — branch `feat/platform-m1-m3`
- test_decimal_price_filters_serialize_on_the_wire
- test_packaging.py
- crucible

## God Nodes (most connected - your core abstractions)
1. `Product` - 64 edges
2. `TaskSpec` - 60 edges
3. `CatalogProvider` - 54 edges
4. `TaskSplit` - 50 edges
5. `EpisodeRecord` - 39 edges
6. `run_episode()` - 39 edges
7. `ProviderRouter` - 39 edges
8. `GuardedPayments` - 38 edges
9. `MockPayments` - 38 edges
10. `create_app()` - 35 edges

## Surprising Connections (you probably didn't know these)
- `Evaluation` --references--> `EpisodeRecord`  [INFERRED]
  docs/spikes/core-engine.md → agents/actions.py
- `4. Required skills and dev tooling` --references--> `Channel3Provider`  [INFERRED]
  prompt.md → catalog/providers/channel3.py
- `Recommended provider chain (for the integration owner)` --references--> `ElasticCatalogProvider`  [INFERRED]
  docs/spikes/catalog-elastic.md → catalog/providers/elastic.py
- `Scorecard` --references--> `OrderNotApproved`  [INFERRED]
  docs/spikes/platform-day1.md → payments/errors.py
- `2026-10-30 scaffold` --references--> `PriceMismatch`  [INFERRED]
  DECISIONS.md → payments/guards.py

## Import Cycles
- None detected.

## Communities (69 total, 21 thin omitted)

### Community 0 - "TaskSpec"
Cohesion: 0.05
Nodes (85): CatalogProvider, Determinism and assumptions, Initial rule registry, Integration requirements, Reproducible checks, Scoring contracts spike, calculate_efficiency_penalty(), calculate_fitness() (+77 more)

### Community 1 - "TaskSplit"
Cohesion: 0.05
Nodes (51): EpisodeRecord, InMemoryMemoryProvider, MemoryProvider, RetrievalRequest, Assumptions and blockers, Contracts Agent 1 must implement or integrate, Core status handoff, Next phase (+43 more)

### Community 2 - "runner.py"
Cohesion: 0.09
Nodes (50): ActionModel, Compare, ConfirmAndPay, EpisodeTermination, GetProduct, GetReviews, ParseIntent, ProposePurchase (+42 more)

### Community 3 - "run_generation"
Cohesion: 0.07
Nodes (44): 2026-11-01 integration/runtime owner: measured results, CheckpointConflict, CheckpointCorrupt, CheckpointStore, _digest(), GenerationReport, run_generation(), training_catalog() (+36 more)

### Community 4 - "qwen_toolcalls.py"
Cohesion: 0.08
Nodes (33): checkpoint_resume_probe(), checkpoint_steps(), _download_model(), inspect_checkpoint(), run_tool_call_probe(), _sanitize(), _state_path(), tool_call_probe() (+25 more)

### Community 5 - "harness.py"
Cohesion: 0.07
Nodes (27): Amazon Reviews 2023 (measured), Channel3 (documentation findings), Coverage table (sample; "usable" = real price and >= 5 real reviews held in the sample), Day-1 spike: catalog provider, Elastic hybrid search, review coverage, Recommended provider chain (for the integration owner), Review-trap eligibility (recommendation), Shoe attribute probe (rerun), Status (+19 more)

### Community 6 - "guards.py"
Cohesion: 0.14
Nodes (20): Contracts agent 2 can consume (no Elastic import needed), Action order, Tool contract, BudgetViolation, GuardViolation, NotConfirmed, OutOfStock, PendingOrder (+12 more)

### Community 7 - "ElasticCatalogProvider"
Cohesion: 0.10
Nodes (17): ElasticCatalogProvider, hybrid_review_query(), mappings(), _product(), _vec(), Elastic (offline-verified only), Channel3 (live, 16 calls / 12 credits), Decisions taken (+9 more)

### Community 8 - "SandboxPayments"
Cohesion: 0.10
Nodes (14): 1. OAuth (verified live), 2. Orders v2 (`payments/sandbox.py`), 3. Contract tests, 4. PayPal Agent Toolkit / MCP (check 2), 6. Pending (blocked on buyer credentials), Blockers, Spike: PayPal sandbox checkout + Agent Toolkit + Kernel approval (Day-1 checks 1–3), AmountMismatch (+6 more)

### Community 9 - "hashlib"
Cohesion: 0.11
Nodes (17): Scoring, episode_seed(), DeterministicFakeJudge, input_hash(), Judge, JudgeResult, catalog_manifest_hash(), test_fake_judge_is_versioned_hashed_cached_and_fails_closed() (+9 more)

### Community 10 - "MockPayments"
Cohesion: 0.13
Nodes (5): Capture, OrderNotApproved, OrderNotFound, PaymentError, MockPayments

### Community 11 - "Product"
Cohesion: 0.11
Nodes (6): Product, Review, Boundary, Snap, Snap, Snap

### Community 12 - "ProviderRouter"
Cohesion: 0.15
Nodes (7): ProductResult, ProviderRouter, ProviderUnavailable, ReviewsResult, Routed, SearchResult, Suggested Questions

### Community 13 - "sources/snapshot.py"
Cohesion: 0.14
Nodes (13): coverage(), iter_jsonl(), meta_url(), parse_price(), review_url(), source_revision(), attr_probe(), main() (+5 more)

### Community 14 - "Communities (26 total, 10 thin omitted)"
Cohesion: 0.08
Nodes (25): Communities (26 total, 10 thin omitted), Community 0 - "test_payments_contract.py", Community 10 - "create_app", Community 11 - "test_catalog_router.py", Community 12 - "Graph Report - Crucible   (2026-10-30)", Community 13 - "main.py", Community 15 - "router.py", Community 16 - "test_api_endpoints.py" (+17 more)

### Community 15 - "pytest"
Cohesion: 0.14
Nodes (12): _Catalog, Rig, _sandbox(), test_budget_rejected_before_any_api_call(), test_error_mapping_capture_before_approval_and_unknown_order(), test_inexact_or_nonpositive_amount_rejected(), test_no_capture_call_without_explicit_confirmation(), test_sandbox_amount_mismatch_is_caught() (+4 more)

### Community 16 - "test_payments_quote.py"
Cohesion: 0.16
Nodes (16): SnapshotListPriceQuoter, Cat, guarded(), propose(), Quoter, reset(), SpyBackend, test_agent_quoting_the_list_price_is_a_price_mismatch_not_a_cheaper_charge() (+8 more)

### Community 17 - "create_app"
Cohesion: 0.14
Nodes (16): create_app(), confirm(), get_payments(), get_router(), _guard(), _payment(), product(), propose() (+8 more)

### Community 18 - "Elastic"
Cohesion: 0.21
Nodes (10): default_router(), Elastic, endpoint_from_cloud_id(), main(), elastic(), main(), main(), t() (+2 more)

### Community 19 - "test_kernel_approver.py"
Cohesion: 0.15
Nodes (8): 5. Kernel buyer approval (check 1a), ApprovalBlocked, KernelApprover, FakeBackend, FakeKernel, test_approves_and_always_deletes_browser(), test_challenge_stops_run(), test_errors_never_contain_credentials()

### Community 20 - "main.py"
Cohesion: 0.13
Nodes (9): ConfirmRequest, ConfirmResponse, ErrorBody, ErrorResponse, ProposeRequest, ProposeResponse, ProviderStatus, Quote (+1 more)

### Community 22 - "indexing.py"
Cohesion: 0.18
Nodes (11): join(), product_doc(), record_sha256(), review_doc(), review_id(), sample_stats(), source_review_key(), test_duplicate_source_rows_get_distinct_stable_ids_and_keep_the_original_key() (+3 more)

### Community 23 - "Channel3Provider"
Cohesion: 0.22
Nodes (8): build_filters(), Channel3Provider, to_product(), channel3(), fake(), test_filters_map_price_and_passthrough(), test_product_detail_free_and_reviews_none(), test_search_costs_one_credit_maps_product_and_skips_priceless()

### Community 25 - "json"
Cohesion: 0.22
Nodes (7): has_key(), load_env(), main(), stats(), main(), training_catalog(), main()

### Community 26 - "Build Spec: Crucible — an evolutionary RL world that trains open models to shop on PayPal"
Cohesion: 0.12
Nodes (17): 0. Ground rules for you (read first), 11. Data terms and compliance, 12. Evaluation, 13. Repository layout, 14. Non-functional requirements, 15. Day-1 kill-checks (do these first; report results before building further), 16. Milestones (deadline Nov 12, 12:00 PM PT), 17. Definition of done (+9 more)

### Community 27 - "build_task"
Cohesion: 0.24
Nodes (10): assign_split(), build_review_trap(), build_task(), render_request(), SplitConfig, constraints(), test_feasible_set_and_task_generation_are_seeded_and_stable(), test_review_traps_require_real_product_scoped_review_ids() (+2 more)

### Community 28 - "build"
Cohesion: 0.21
Nodes (10): build(), stream_jsonl(), meta(), rev(), run(), test_deterministic_hash(), test_duplicate_source_rows_stay_distinct_in_a_snapshot(), test_keeps_only_priced_products_with_enough_real_reviews() (+2 more)

### Community 29 - "test_catalog_router.py"
Cohesion: 0.20
Nodes (10): Fake, router(), test_bestbuy_disabled_cannot_be_routed(), test_live_falls_back_to_snapshot_and_says_so(), test_live_uses_channel3_not_labelled_snapshot(), test_missing_reviews_are_none_not_invented(), test_router_refilters_price_cap(), test_snapshot_reviews_carry_source() (+2 more)

### Community 30 - "PaymentsBackend"
Cohesion: 0.14
Nodes (6): reviews(), Surprising Connections (you probably didn't know these), PaymentsBackend, QuoteProvider, 7.1 How each integration works (implementation detail), 7. Infrastructure: every service, what it does, and exactly how we use it

### Community 31 - "engine.py"
Cohesion: 0.24
Nodes (10): Task computation, compute_feasible_set(), FeasibilityResult, implied_needs_fit(), _matches(), select_best_value(), select_closest(), distance() (+2 more)

### Community 32 - "test_api_endpoints.py"
Cohesion: 0.24
Nodes (13): client(), test_capture_needs_explicit_confirmation_then_approval(), test_confirm_after_approval_captures_exact_amount(), test_over_budget_rejected_before_order(), test_price_mismatch_rejected(), test_propose_returns_the_all_in_quote_and_discloses_its_basis(), test_provider_status_shows_bestbuy_disabled(), test_reviews_and_missing_product() (+5 more)

### Community 33 - "tasks/schemas.py"
Cohesion: 0.25
Nodes (7): Ambiguity, AttributeConstraint, ConstraintOperator, ContractModel, ResearchRequirements, ReviewPolarity, ReviewSignal

### Community 34 - "test_catalog_enumeration.py"
Cohesion: 0.25
Nodes (9): FakeEs, prod(), provider(), rev(), test_empty_query_is_not_enumeration(), test_get_reviews_without_focus_honours_limits_above_the_window(), test_iter_products_is_complete_sorted_and_category_scoped(), test_review_ids_do_not_truncate_at_10000() (+1 more)

### Community 35 - "generate_tasks"
Cohesion: 0.33
Nodes (9): generate_tasks(), make(), _quantile(), catalog(), test_feasible_sets_are_real_and_impossible_tasks_have_a_real_closest_product(), test_impossible_mix_is_exact_not_sampled(), test_intended_feasible_tasks_are_not_accidentally_impossible(), test_tasks_come_from_the_training_snapshot_enumeration_and_are_deterministic() (+1 more)

### Community 36 - "migrate_review_ids.py"
Cohesion: 0.27
Nodes (6): legacy_record(), migrate_docs(), rehash_manifests(), legacy(), test_identical_legacy_rows_become_two_distinct_ids_and_keep_the_original_key(), test_legacy_record_roundtrips_the_source_fields()

### Community 37 - "providers/elastic.py"
Cohesion: 0.23
Nodes (4): _review(), HttpError, _num(), request_json()

### Community 38 - "TrainingCatalog"
Cohesion: 0.35
Nodes (8): TrainingCatalog, Live, router(), test_empty_query_with_category_enumerates_completely_in_id_order(), test_enumeration_applies_price_cap_and_requires_a_category(), test_live_provider_cannot_enumerate(), test_nonempty_query_is_ranked_search_not_enumeration(), test_training_view_never_reaches_live_provider_and_rejects_live_mode()

### Community 39 - "Decisions"
Cohesion: 0.18
Nodes (11): 2026-10-30 Day-1 check 4b/8 (partial): Amazon Reviews 2023 coverage, 2026-10-30 scaffold, 2026-10-31 integration owner: security, skills, Astropods (Day-1 checks 9, 10), 2026-10-31 platform owner (agent 1): Day-1 provider and infrastructure decisions, Astropods (check 9) — from docs.astropods.com, Day-1 kill-checks (spec 15): NOT RUN, Decisions, Integration status (+3 more)

### Community 40 - "Architecture"
Cohesion: 0.18
Nodes (11): Architecture, Catalog provider selection, Checkout, Data model, Deployment topology, Evolution loop, Integration/runtime layer (measured 2026-11-01), One episode (+3 more)

### Community 41 - "Deterministic core engine"
Cohesion: 0.18
Nodes (8): Deterministic core engine, Evaluation, Evolution and resume, Fixture limitations, Initial kill registry, Invariants, Leakage and curation, ConstraintEvidence

### Community 42 - "README.md"
Cohesion: 0.20
Nodes (5): Crucible, Explicitly incomplete, Infrastructure status, Reproducible commands, Setup

### Community 43 - "LeakageGuard"
Cohesion: 0.22
Nodes (6): External calls and cost, Integration/runtime status — branch `feat/integration-runtime`, Reproduce, Things agent 2 / the user must decide, LeakageGuard, test_leakage_guard_protects_test_products()

### Community 44 - "8. Component build specs"
Cohesion: 0.20
Nodes (10): 8.1 Catalog snapshot (`catalog/`), 8.2 Task generator (`tasks/`), 8.3 Agent tools (action space), 8.4 PayPal layer (`payments/`), 8.5 Population and evolution (`world/`), 8.6 Scoring (`scoring/`), 8.7 Loophole Hunter (`world/loophole_hunter.py`), 8.8 Trace store and memory (`memory/`) (+2 more)

### Community 46 - "contenders.py"
Cohesion: 0.32
Nodes (3): Contender, WebShopAdapter, WebShopNotConfigured

### Community 47 - "6. Architecture (mapped out)"
Cohesion: 0.25
Nodes (8): 6.1 System context, 6.2 Catalog provider selection (fallback chain), 6.3 One episode (agent ↔ world), 6.4 Evolution loop, 6.5 Checkout (sandbox, no human click), 6.6 Training and evaluation pipeline, 6.7 Deployment topology, 6. Architecture (mapped out)

### Community 49 - "10. Product surface and design direction"
Cohesion: 0.29
Nodes (7): 10.1 Design direction, 10.2 Shopping Chat (hero), 10.3 World Dashboard, 10.4 Model Dashboard, 10.5 Reference visuals (look, don't copy), 10.6 Docs and visuals we must produce, 10. Product surface and design direction

### Community 51 - "HardConstraints"
Cohesion: 0.52
Nodes (6): Difficulty, HardConstraints, task(), test_feasibility_references_are_internally_consistent(), test_impossible_task_requires_a_closest_real_product(), test_task_contract_is_strict_and_immutable()

### Community 53 - "Platform status (agent 1) — branch `feat/platform-m1-m3`"
Cohesion: 0.33
Nodes (6): Blockers needing the user, Decisions awaiting integration, Environment names, External calls and approximate cost, Platform status (agent 1) — branch `feat/platform-m1-m3`, Requested from agent 2 (documented only; nothing edited in their dirs)

## Knowledge Gaps
- **1 isolated node(s):** `crucible`
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 422 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **21 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Product` connect `Product` to `TaskSpec`, `runner.py`, `guards.py`, `ElasticCatalogProvider`, `hashlib`, `ProviderRouter`, `Communities (26 total, 10 thin omitted)`, `pytest`, `test_payments_quote.py`, `decimal`, `Channel3Provider`, `build_task`, `test_catalog_router.py`, `engine.py`, `test_api_endpoints.py`, `generate_tasks`, `providers/elastic.py`, `TrainingCatalog`, `SnapshotCatalog`, `Snap`?**
  _High betweenness centrality (0.075) - this node is a cross-community bridge._
- **Are the 26 inferred relationships involving `Product` (e.g. with `Channel3Provider` and `ElasticCatalogProvider`) actually correct?**
  _`Product` has 26 INFERRED edges - model-reasoned connections that need verification._
- **What connects `crucible` to the rest of the system?**
  _1 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `TaskSpec` be split into smaller, more focused modules?**
  _Cohesion score 0.05126646403242148 - nodes in this community are weakly interconnected._
- **Why does `Build Spec: Crucible — an evolutionary RL world that trains open models to shop on PayPal` connect `Build Spec: Crucible — an evolutionary RL world that trains open models to shop on PayPal` to `README.md`, `8. Component build specs`, `6. Architecture (mapped out)`, `10. Product surface and design direction`, `PaymentsBackend`?**
  _High betweenness centrality (0.069) - this node is a cross-community bridge._
- **Are the 30 inferred relationships involving `TaskSpec` (e.g. with `ActionPolicy` and `run_episode()`) actually correct?**
  _`TaskSpec` has 30 INFERRED edges - model-reasoned connections that need verification._
- **Should `TaskSplit` be split into smaller, more focused modules?**
  _Cohesion score 0.051058046981168705 - nodes in this community are weakly interconnected._