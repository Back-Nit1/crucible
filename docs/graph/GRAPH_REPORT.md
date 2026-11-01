# Graph Report - Crucible-integration  (2026-10-31)

## Corpus Check
- 157 files · ~166,161 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 5 file(s) not represented in the graph (top: (none) 3, .example 1, .lock 1)

## Summary
- 1543 nodes · 4639 edges · 81 communities (58 shown, 23 thin omitted)
- Extraction: 88% EXTRACTED · 12% INFERRED · 0% AMBIGUOUS · INFERRED: 579 edges (avg confidence: 0.93)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `34d0e7db`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- TaskSpec
- tasks/schemas.py
- pytest
- Elastic
- harness.py
- json
- Build Spec: Crucible — an evolutionary RL world that trains open models to shop on PayPal
- runner.py
- Product
- qwen_toolcalls.py
- TaskSplit
- evolution.py
- test_world_runtime.py
- store.py
- day1_coverage.py
- snapshot.py
- run_episode
- create_app
- world.py
- indexing.py
- providers/elastic.py
- test_payments_contract.py
- GenerationStore
- main.py
- scripted.py
- test_memory_episodes.py
- test_api_world.py
- sandbox.py
- day1_probe.py
- world_router
- test_catalog_frozen.py
- Channel3Provider
- test_catalog_router.py
- SandboxPayments
- test_api_endpoints.py
- world_runner.py
- KernelApprover
- Communities (26 total, 10 thin omitted)
- TraceRecord
- Graph Report - Crucible-platform  (2026-10-31)
- ProviderRouter
- test_memory_retrieval.py
- curation.py
- judge.py
- runtime.py
- readers.py
- test_world_remote.py
- FileBlobStore
- MockPayments
- router.py
- FrozenCache
- typing
- Architecture
- AmountMismatch
- Capture
- ElasticReader
- Generation gen-20261101-p8-t12
- FakePayPal
- day1_live.py
- BlobStore
- Decisions
- GenerationCheckpoint
- Platform status (agent 1) — branch `feat/platform-m1-m3`
- Runtime / integration status (Agent 1) — branch `feat/operational-world`
- Deployment foundation
- Crucible
- 2026-10-31 integration owner: security, skills, Astropods (Day-1 checks 9, 10)
- test_modal_world_runner.py
- crucible

## God Nodes (most connected - your core abstractions)
1. `Product` - 67 edges
2. `TaskSpec` - 62 edges
3. `create_app()` - 52 edges
4. `FrozenCatalogProvider` - 50 edges
5. `Elastic` - 42 edges
6. `TaskSplit` - 42 edges
7. `InMemoryCatalog` - 42 edges
8. `MockPayments` - 39 edges
9. `GuardedPayments` - 38 edges
10. `EpisodeRecord` - 37 edges

## Surprising Connections (you probably didn't know these)
- `Evaluation` --references--> `EpisodeRecord`  [INFERRED]
  docs/spikes/core-engine.md → agents/actions.py
- `Phase status` --references--> `MemoryProvider`  [INFERRED]
  docs/handoffs/core-status.md → agents/memory.py
- `4. Required skills and dev tooling` --references--> `Channel3Provider`  [INFERRED]
  prompt.md → catalog/providers/channel3.py
- `Recommended provider chain (for the integration owner)` --references--> `ElasticCatalogProvider`  [INFERRED]
  docs/spikes/catalog-elastic.md → catalog/providers/elastic.py
- `Scorecard` --references--> `OrderNotApproved`  [INFERRED]
  docs/spikes/platform-day1.md → payments/errors.py

## Import Cycles
- None detected.

## Communities (81 total, 23 thin omitted)

### Community 0 - "TaskSpec"
Cohesion: 0.05
Nodes (81): FrozenCatalogProvider, Determinism and assumptions, Initial rule registry, Integration requirements, Reproducible checks, Scoring contracts spike, calculate_efficiency_penalty(), calculate_fitness() (+73 more)

### Community 1 - "tasks/schemas.py"
Cohesion: 0.05
Nodes (51): Deterministic core engine, Evaluation, Evolution and resume, Fixture limitations, Initial kill registry, Invariants, Leakage and curation, Task computation (+43 more)

### Community 2 - "pytest"
Cohesion: 0.06
Nodes (50): Operational world (integration, `feat/operational-world`), Contracts agent 2 can consume (no Elastic import needed), Contracts Agent 2 can consume, Action order, Tool contract, BudgetViolation, GuardViolation, NotConfirmed (+42 more)

### Community 3 - "Elastic"
Cohesion: 0.07
Nodes (23): default_router(), Elastic, ElasticCatalogProvider, endpoint_from_cloud_id(), hybrid_review_query(), load_manifest_hashes(), _product(), Elastic (offline-verified only) (+15 more)

### Community 4 - "harness.py"
Cohesion: 0.05
Nodes (37): Assumptions and blockers, Core status handoff, Next phase, Phase status, Suggested shared documentation changes, Verification, Amazon Reviews 2023 (measured), Channel3 (documentation findings) (+29 more)

### Community 5 - "json"
Cohesion: 0.11
Nodes (10): default_reader(), snapshot_digest(), ApprovalBlocked, load(), main(), main(), ms(), live_snapshots() (+2 more)

### Community 6 - "Build Spec: Crucible — an evolutionary RL world that trains open models to shop on PayPal"
Cohesion: 0.05
Nodes (42): 0. Ground rules for you (read first), 10.1 Design direction, 10.2 Shopping Chat (hero), 10.3 World Dashboard, 10.4 Model Dashboard, 10.5 Reference visuals (look, don't copy), 10.6 Docs and visuals we must produce, 10. Product surface and design direction (+34 more)

### Community 7 - "runner.py"
Cohesion: 0.28
Nodes (28): ActionModel, Compare, ConfirmAndPay, GetProduct, GetReviews, ParseIntent, ProposePurchase, RecordedToolCall (+20 more)

### Community 8 - "Product"
Cohesion: 0.09
Nodes (9): CatalogProvider, Product, Review, ReviewIds, SnapshotMismatch, Boundary, SyntheticFrozen, Snap (+1 more)

### Community 9 - "qwen_toolcalls.py"
Cohesion: 0.13
Nodes (24): arguments_are_schema_valid(), estimate_modal_cost(), _object_schema(), parse_tool_calls(), ParsedToolCall, ParseResult, percentile(), prompt_manifest() (+16 more)

### Community 10 - "TaskSplit"
Cohesion: 0.16
Nodes (12): EpisodeRecord, InMemoryMemoryProvider, MemoryProvider, RetrievalRequest, RepositoryMemoryProvider, eligible(), TaskSplit, episode() (+4 more)

### Community 11 - "evolution.py"
Cohesion: 0.17
Nodes (19): test_killed_agents_cannot_reproduce_and_survivors_are_elites(), test_mutations_stay_in_ranges_and_parent_references_exist(), test_seeded_population_selection_and_hashes_are_stable(), breed_generation(), DeterministicMutationProposer, Genome, genome_hash(), _genome_id() (+11 more)

### Community 12 - "test_world_runtime.py"
Cohesion: 0.11
Nodes (10): InMemoryTraceRepository, run(), test_a_crash_mid_generation_marks_failed_and_releases_the_lock(), test_full_generation_survives_kills_fixtures_and_never_buys_badly(), test_interrupt_then_resume_runs_each_pair_exactly_once_and_matches_an_uninterrupted_run(), test_population_has_honest_agents_and_one_fixture_per_kill_rule(), world(), build_population() (+2 more)

### Community 13 - "store.py"
Cohesion: 0.14
Nodes (18): fresh(), out(), test_corrupted_checkpoints_are_rejected(), test_finalize_refuses_incomplete_generation(), test_hash_covers_content_so_encode_is_deterministic(), test_incompatible_versions_are_rejected(), test_resume_schedules_only_remaining_pairs_and_never_repeats_completed(), test_single_writer_lease() (+10 more)

### Community 14 - "day1_coverage.py"
Cohesion: 0.13
Nodes (12): coverage(), iter_jsonl(), parse_price(), attr_probe(), main(), seg_text(), size_of(), windows() (+4 more)

### Community 15 - "snapshot.py"
Cohesion: 0.16
Nodes (14): meta_url(), review_url(), build(), source_revision(), stream_jsonl(), main(), meta(), rev() (+6 more)

### Community 16 - "run_episode"
Cohesion: 0.10
Nodes (9): EpisodeTermination, ActionPolicy, ModelStep, run_episode(), RunnerConfig, ScriptedPolicy, InvalidActionOrder, test_invalid_order_terminates_without_payment() (+1 more)

### Community 17 - "create_app"
Cohesion: 0.15
Nodes (20): create_app(), confirm(), get_payments(), get_router(), _guard(), _http(), _no_model(), _no_world() (+12 more)

### Community 18 - "world.py"
Cohesion: 0.13
Nodes (14): AgentRunner, AgentRunRequest, _detail(), _episode(), EpisodeDetail, EpisodeOut, KillOut, KillRuleOut (+6 more)

### Community 19 - "indexing.py"
Cohesion: 0.17
Nodes (12): join(), legacy_to_canonical(), product_doc(), record_sha256(), review_doc(), review_id(), sample_stats(), source_review_key() (+4 more)

### Community 20 - "providers/elastic.py"
Cohesion: 0.11
Nodes (10): mappings(), _review(), _vec(), HttpError, _num(), request_json(), Elastic Serverless (live), counting() (+2 more)

### Community 21 - "test_payments_contract.py"
Cohesion: 0.13
Nodes (10): _Catalog, Rig, _sandbox(), test_budget_rejected_before_any_api_call(), test_inexact_or_nonpositive_amount_rejected(), test_sandbox_amount_mismatch_is_caught(), test_sandbox_declined_capture_and_already_captured_replay(), test_sandbox_refreshes_token_once_on_401_and_never_leaks_secret() (+2 more)

### Community 22 - "GenerationStore"
Cohesion: 0.24
Nodes (7): test_file_write_is_atomic_when_the_new_state_cannot_be_written(), test_volume_hooks_run_on_write_and_before_read(), GenerationSummary, run_generation(), RunResult, GenerationState, GenerationStore

### Community 23 - "main.py"
Cohesion: 0.13
Nodes (9): configure_logging(), ConfirmRequest, ConfirmResponse, ErrorBody, ErrorResponse, _LazyReader, ProposeRequest, ProposeResponse (+1 more)

### Community 24 - "scripted.py"
Cohesion: 0.20
Nodes (11): build_script(), _excerpt(), _intent(), _over_budget(), _purchase(), _research(), _reviews(), scripted_policy() (+3 more)

### Community 25 - "test_memory_episodes.py"
Cohesion: 0.16
Nodes (10): episode_from_trace(), _first(), trace_from_episode(), GuardedPayments, idempotency_key(), run(), test_elastic_repository_fails_closed_on_malformed_and_ineligible_hits(), test_killed_trace_keeps_rule_version_and_evidence() (+2 more)

### Community 26 - "test_api_world.py"
Cohesion: 0.19
Nodes (7): AgentRunResult, PickOut, ReplayStep, ReviewEvidenceOut, client(), FakeRunner, traces()

### Community 27 - "sandbox.py"
Cohesion: 0.17
Nodes (6): OrderNotApproved, OrderNotFound, PaymentError, money(), test_error_mapping_capture_before_approval_and_unknown_order(), test_money_formats_two_decimals_never_float()

### Community 28 - "day1_probe.py"
Cohesion: 0.17
Nodes (9): checkpoint_resume_probe(), checkpoint_steps(), _download_model(), inspect_checkpoint(), run_tool_call_probe(), _sanitize(), _state_path(), tool_call_probe() (+1 more)

### Community 29 - "world_router"
Cohesion: 0.14
Nodes (16): DocumentOut, GenerationDetail, GenerationOut, KillLogRow, LeaderboardRow, LedgerRow, world_router(), checkpoints() (+8 more)

### Community 30 - "test_catalog_frozen.py"
Cohesion: 0.22
Nodes (11): IncompleteReviewIds, FakeEs, prod(), provider(), rev(), test_amazon_products_never_expose_stock_or_size_even_if_a_doc_carries_it(), test_iter_products_is_ordered_complete_and_stamped_with_snapshot_provenance(), test_iter_products_rejects_unknown_manifest_hash() (+3 more)

### Community 31 - "Channel3Provider"
Cohesion: 0.22
Nodes (7): build_filters(), Channel3Provider, to_product(), fake(), test_filters_map_price_and_passthrough(), test_product_detail_free_and_reviews_none(), test_search_costs_one_credit_maps_product_and_skips_priceless()

### Community 32 - "test_catalog_router.py"
Cohesion: 0.18
Nodes (11): ProviderUnavailable, Fake, router(), test_bestbuy_disabled_cannot_be_routed(), test_live_falls_back_to_snapshot_and_says_so(), test_live_uses_channel3_not_labelled_snapshot(), test_missing_reviews_are_none_not_invented(), test_router_refilters_price_cap() (+3 more)

### Community 33 - "SandboxPayments"
Cohesion: 0.19
Nodes (4): PaymentDeclined, SandboxPayments, test_capture_before_approval_is_rejected(), test_create_is_idempotent_and_exact_amount()

### Community 34 - "test_api_endpoints.py"
Cohesion: 0.18
Nodes (13): client(), test_capture_needs_explicit_confirmation_then_approval(), test_confirm_after_approval_captures_exact_amount(), test_over_budget_rejected_before_order(), test_price_mismatch_rejected(), test_propose_labels_the_quote_basis_and_never_claims_all_in_for_item_price(), test_provider_status_shows_bestbuy_disabled(), test_require_all_in_env_blocks_item_price_only_checkout() (+5 more)

### Community 35 - "world_runner.py"
Cohesion: 0.15
Nodes (9): main(), run_remote(), scheduled_resume(), status_remote(), _store(), generation_doc(), kill_rule_docs(), publish_generation() (+1 more)

### Community 36 - "KernelApprover"
Cohesion: 0.18
Nodes (6): KernelApprover, FakeBackend, FakeKernel, test_approves_and_always_deletes_browser(), test_challenge_stops_run(), test_errors_never_contain_credentials()

### Community 37 - "Communities (26 total, 10 thin omitted)"
Cohesion: 0.12
Nodes (17): Communities (26 total, 10 thin omitted), Community 0 - "test_payments_contract.py", Community 10 - "create_app", Community 11 - "test_catalog_router.py", Community 12 - "Graph Report - Crucible   (2026-10-30)", Community 13 - "main.py", Community 15 - "router.py", Community 16 - "test_api_endpoints.py" (+9 more)

### Community 39 - "Graph Report - Crucible-platform  (2026-10-31)"
Cohesion: 0.14
Nodes (14): reviews(), kill_rules(), Community Hubs (Navigation), Corpus Check, God Nodes (most connected - your core abstractions), Graph Freshness, Graph Report - Crucible-platform  (2026-10-31), Import Cycles (+6 more)

### Community 41 - "test_memory_retrieval.py"
Cohesion: 0.21
Nodes (10): similar_query(), repo(), test_add_is_idempotent_per_episode(), test_elastic_query_carries_leakage_filter(), test_elastic_repo_sends_filtered_knn_without_importing_elastic_in_callers(), call(), test_killed_and_low_fitness_excluded(), test_most_similar_first_and_k_respected() (+2 more)

### Community 42 - "curation.py"
Cohesion: 0.25
Nodes (10): test_curation_excludes_evaluation_killed_invalid_and_duplicates_with_stable_manifest(), curate_survivors(), CurationResult, _grounded(), _normalized(), _record(), _reviews_valid(), SFTRecord (+2 more)

### Community 43 - "judge.py"
Cohesion: 0.22
Nodes (6): Scoring, DeterministicFakeJudge, input_hash(), Judge, JudgeResult, test_fake_judge_is_versioned_hashed_cached_and_fails_closed()

### Community 44 - "runtime.py"
Cohesion: 0.18
Nodes (4): TraceRepository, compat_for(), make_clock(), Compat

### Community 45 - "readers.py"
Cohesion: 0.20
Nodes (4): InMemoryReader, _key(), _match(), test_agent_run_contract_and_unconfigured_model_is_a_clear_503()

### Community 46 - "test_world_remote.py"
Cohesion: 0.29
Nodes (8): put(), test_cost_is_wall_time_times_list_price(), test_status_lists_every_generation_and_flags_corruption_and_scheduler_resumes_only_unfinished(), approx_cost_usd(), brief(), latest_unfinished(), status(), timed()

### Community 49 - "router.py"
Cohesion: 0.25
Nodes (5): load_config(), ProductResult, ReviewsResult, Routed, SearchResult

### Community 51 - "typing"
Cohesion: 0.24
Nodes (3): Contender, WebShopAdapter, WebShopNotConfigured

### Community 52 - "Architecture"
Cohesion: 0.20
Nodes (10): Architecture, Catalog provider selection, Checkout, Data model, Deployment topology, Evolution loop, One episode, Platform implementation status (milestones 1-3, agent 1) (+2 more)

### Community 53 - "AmountMismatch"
Cohesion: 0.20
Nodes (9): 1. OAuth (verified live), 2. Orders v2 (`payments/sandbox.py`), 3. Contract tests, 4. PayPal Agent Toolkit / MCP (check 2), 5. Kernel buyer approval (check 1a), 6. Pending (blocked on buyer credentials), Blockers, Spike: PayPal sandbox checkout + Agent Toolkit + Kernel approval (Day-1 checks 1–3) (+1 more)

### Community 56 - "Generation gen-20261101-p8-t12"
Cohesion: 0.25
Nodes (8): Episodes, Fitness, Generation gen-20261101-p8-t12, Kills, Loophole Hunter (proposals only, none enabled), Safety, Tasks, Training curation

### Community 58 - "day1_live.py"
Cohesion: 0.43
Nodes (5): channel3(), has_key(), load_env(), main(), stats()

### Community 60 - "Decisions"
Cohesion: 0.29
Nodes (7): 2026-10-30 Day-1 check 4b/8 (partial): Amazon Reviews 2023 coverage, 2026-10-30 scaffold, 2026-10-31 integration owner (agent 1): operational world, 2026-10-31 platform owner (agent 1): Day-1 provider and infrastructure decisions, Day-1 kill-checks (spec 15): NOT RUN, Decisions, Tooling versions (2026-10-30)

### Community 61 - "GenerationCheckpoint"
Cohesion: 0.43
Nodes (3): Contracts Agent 1 must implement or integrate, test_checkpoint_resume_is_idempotent_and_hash_stable(), GenerationCheckpoint

### Community 62 - "Platform status (agent 1) — branch `feat/platform-m1-m3`"
Cohesion: 0.29
Nodes (6): Blockers needing the user, Decisions awaiting integration, Environment names, External calls and approximate cost, Platform status (agent 1) — branch `feat/platform-m1-m3`, Requested from agent 2 (documented only; nothing edited in their dirs)

### Community 63 - "Runtime / integration status (Agent 1) — branch `feat/operational-world`"
Cohesion: 0.29
Nodes (6): Environment names, External calls and cost (this branch), Findings for Agent 2, Phase log, Reproduce, Runtime / integration status (Agent 1) — branch `feat/operational-world`

### Community 64 - "Deployment foundation"
Cohesion: 0.33
Nodes (5): Commands, Deployment foundation, Environment-variable inventory, Observability, Services

### Community 65 - "Crucible"
Cohesion: 0.33
Nodes (6): Crucible, Explicitly incomplete, Infrastructure status, Operational world (integration branch), Reproducible commands, Setup

### Community 67 - "2026-10-31 integration owner: security, skills, Astropods (Day-1 checks 9, 10)"
Cohesion: 0.40
Nodes (5): 2026-10-31 integration owner: security, skills, Astropods (Day-1 checks 9, 10), Astropods (check 9) — from docs.astropods.com, Integration status, Secret hygiene, Skills (check 10)

## Knowledge Gaps
- **1 isolated node(s):** `crucible`
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 495 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **23 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Product` connect `Product` to `TaskSpec`, `tasks/schemas.py`, `pytest`, `Elastic`, `test_api_endpoints.py`, `test_catalog_router.py`, `Graph Report - Crucible-platform  (2026-10-31)`, `ProviderRouter`, `router.py`, `providers/elastic.py`, `test_payments_contract.py`, `scripted.py`, `Channel3Provider`?**
  _High betweenness centrality (0.075) - this node is a cross-community bridge._
- **Are the 32 inferred relationships involving `Product` (e.g. with `Channel3Provider` and `ElasticCatalogProvider`) actually correct?**
  _`Product` has 32 INFERRED edges - model-reasoned connections that need verification._
- **What connects `crucible` to the rest of the system?**
  _1 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `TaskSpec` be split into smaller, more focused modules?**
  _Cohesion score 0.05366643534582466 - nodes in this community are weakly interconnected._
- **Why does `Build Spec: Crucible — an evolutionary RL world that trains open models to shop on PayPal` connect `Build Spec: Crucible — an evolutionary RL world that trains open models to shop on PayPal` to `README.md`, `Graph Report - Crucible-platform  (2026-10-31)`?**
  _High betweenness centrality (0.056) - this node is a cross-community bridge._
- **Are the 33 inferred relationships involving `TaskSpec` (e.g. with `ActionPolicy` and `run_episode()`) actually correct?**
  _`TaskSpec` has 33 INFERRED edges - model-reasoned connections that need verification._
- **Should `tasks/schemas.py` be split into smaller, more focused modules?**
  _Cohesion score 0.05351170568561873 - nodes in this community are weakly interconnected._