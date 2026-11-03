# Graph Report - crucible-agent-a  (2026-11-03)

## Corpus Check
- 359 files · ~507,982 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 12 file(s) not represented in the graph (top: (none) 6, .example 2, .jsonl 2)

## Summary
- 3536 nodes · 11228 edges · 152 communities (129 shown, 23 thin omitted)
- Extraction: 90% EXTRACTED · 10% INFERRED · 0% AMBIGUOUS · INFERRED: 1156 edges (avg confidence: 0.93)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `c7debae4`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- decimal
- taskgen.py
- datetime
- Elastic
- harness.py
- paypal_live_check.py
- Build Spec: Crucible — an evolutionary RL world that trains open models to shop on PayPal
- test_agent_model_adapter.py
- InMemoryCatalog
- qwen_toolcalls.py
- TaskSplit
- evolution.py
- test_world_model_generation.py
- json
- snapshot.py
- test_catalog_snapshot.py
- agents/runner.py
- create_app
- world.py
- indexing.py
- _http.py
- pytest
- GenerationStore
- main.py
- ScriptUnavailable
- GuardedPayments
- test_api_world.py
- MockPayments
- day1_probe.py
- pathlib
- SnapshotMismatch
- day1_live.py
- ProviderRouter
- SandboxPayments
- test_api_endpoints.py
- run_generation.py
- test_kernel_approver.py
- Communities (81 total, 23 thin omitted)
- types.ts
- God Nodes (most connected - your core abstractions)
- test_eval_runner.py
- TraceRecord
- hashlib
- judge.py
- runtime.py
- test_training_torch_backend.py
- InferenceError
- FileBlobStore
- api/buyer.py
- os
- FrozenCache
- test_eval_manifest.py
- Architecture
- Spike: PayPal sandbox checkout + Agent Toolkit + Kernel approval (Day-1 checks 1–3)
- PaymentsBackend
- test_eval_publish.py
- Generation gen-20261101-p8-t12
- test_api_sandbox.py
- webshop.py
- BlobStore
- Decisions
- test_api_buyer.py
- Platform status (agent 1) — branch `feat/platform-m1-m3`
- Runtime / integration status (Agent 1) — branch `feat/operational-world`
- Deployment foundation
- StatusBadge
- README.md
- episode-grid.tsx
- sys
- planning.py
- crucible
- scoring.py
- test_training_service.py
- TaskSpec
- audit
- agent-workspace.tsx
- ErrorState
- QwenModelAdapter
- train_lora.py
- batch.py
- manifest.json
- test_eval_leakage.py
- review_signals.py
- qwen_probe.py
- tasks/schemas.py
- test_qwen_adapter_inference.py
- test_training_checkpoints.py
- PaymentLedger
- test_payments_guards.py
- CrucibleApi
- Product
- test_tasks_batch.py
- test_training_trainer.py
- package.json
- eval/publish.py
- run_evaluation.py
- test_training_resume.py
- test_qwen_probe.py
- compilerOptions
- SyntheticFrozen
- devDependencies
- test_paypal_live_check.py
- check_submission.py
- SubprocessWebShopEnv
- eval/report.py
- verify
- test_modal_training_module.py
- Ponytail audit (repo-wide, 2026-11-03)
- FakeEngine
- generate-samples.mjs
- Web product status — `feat/web-product`
- re
- test_verify_deploy.py
- scripts
- world/report.py
- Crucible: Devpost text
- QwenInferenceClient
- Modal inference + resumable LoRA training (Agent 1) — branch `feat/modal-training-runtime`
- Day-1 checks 5–6: Qwen tool calling and Modal resumability
- test_check_submission.py
- day1_coverage.py
- Generation fixture-rc-91
- Qwen serving options through December 15
- Generation rc-real-20261102
- Deterministic core engine
- dependencies
- Release convergence (Agent 1) — branch `feat/release-convergence`
- argparse
- rehash_manifests.py
- Model pipeline integration status
- .prettierrc.json
- Crucible web product
- Platform Day-1 findings (agent 1)
- Demo video script (target 2:40, hard limit under 3:00)
- vitest.config.ts
- @playwright/test
- qwen_probe.md
- AGENTS.md
- postcss.config.mjs

## God Nodes (most connected - your core abstractions)
1. `TaskSpec` - 97 edges
2. `Product` - 83 edges
3. `create_app()` - 79 edges
4. `TaskSplit` - 75 edges
5. `FrozenCatalogProvider` - 71 edges
6. `GuardedPayments` - 66 edges
7. `Communities (81 total, 23 thin omitted)` - 59 edges
8. `MockPayments` - 56 edges
9. `InMemoryCatalog` - 56 edges
10. `Elastic` - 53 edges

## Surprising Connections (you probably didn't know these)
- `Evaluation` --references--> `EpisodeRecord`  [INFERRED]
  docs/spikes/core-engine.md → agents/actions.py
- `Phase status` --references--> `MemoryProvider`  [INFERRED]
  docs/handoffs/core-status.md → agents/memory.py
- `Not done / follow-ups` --references--> `ModalQwenClient`  [INFERRED]
  docs/handoffs/measured-evaluation.md → agents/qwen_client.py
- `Render runbook (free plan; the `render` CLI is not installed here, so this is manual)` --references--> `render()`  [INFERRED]
  docs/DEPLOYMENT.md → api/buyer.py
- `2026-11-03 Phase 2 (deploy readiness)` --references--> `render()`  [INFERRED]
  docs/handoffs/release-final-status.md → api/buyer.py

## Import Cycles
- None detected.

## Communities (152 total, 23 thin omitted)

### Community 0 - "decimal"
Cohesion: 0.08
Nodes (26): Boundary, Determinism and assumptions, Initial rule registry, Integration requirements, Reproducible checks, Scoring contracts spike, calculate_fitness(), calculate_quality() (+18 more)

### Community 1 - "taskgen.py"
Cohesion: 0.16
Nodes (17): build_review_trap(), build_task(), compute_feasible_set(), render_request(), HardConstraints, constraints(), test_feasible_set_and_task_generation_are_seeded_and_stable(), test_leakage_guard_protects_test_products() (+9 more)

### Community 2 - "datetime"
Cohesion: 0.05
Nodes (45): Operational world, Reconciliation decisions, Contracts Agent 2 can consume, QuoteChanged, QuoteIncomplete, QuoteStale, ItemPriceQuotes, MockQuotes (+37 more)

### Community 3 - "Elastic"
Cohesion: 0.11
Nodes (15): Elastic, hybrid_review_query(), mappings(), _review(), _vec(), Elastic (offline-verified only), elastic(), t() (+7 more)

### Community 4 - "harness.py"
Cohesion: 0.07
Nodes (34): Amazon Reviews 2023 (measured), Channel3 (documentation findings), Coverage table (sample; "usable" = real price and >= 5 real reviews held in the sample), Day-1 spike: catalog provider, Elastic hybrid search, review coverage, Recommended provider chain (for the integration owner), Review-trap eligibility (recommendation), Shoe attribute probe (rerun), Status (+26 more)

### Community 5 - "paypal_live_check.py"
Cohesion: 0.17
Nodes (7): check(), execute(), main(), raise_blocked(), run_flow(), Steps, timed()

### Community 6 - "Build Spec: Crucible — an evolutionary RL world that trains open models to shop on PayPal"
Cohesion: 0.05
Nodes (41): 0. Ground rules for you (read first), 10.1 Design direction, 10.2 Shopping Chat (hero), 10.3 World Dashboard, 10.4 Model Dashboard, 10.5 Reference visuals (look, don't copy), 10.6 Docs and visuals we must produce, 10. Product surface and design direction (+33 more)

### Community 7 - "test_agent_model_adapter.py"
Cohesion: 0.13
Nodes (54): ActionModel, Compare, ConfirmAndPay, GetProduct, GetReviews, ParseIntent, ProposePurchase, RecordedToolCall (+46 more)

### Community 8 - "InMemoryCatalog"
Cohesion: 0.16
Nodes (13): Review, ReviewIds, evaluate_gate(), GateViolationCode, feasible_task(), InMemoryCatalog, test_gate_passes_for_snapshot_grounded_in_budget_pick(), test_gate_rejects_budget_and_stock_violations() (+5 more)

### Community 9 - "qwen_toolcalls.py"
Cohesion: 0.12
Nodes (25): arguments_are_schema_valid(), estimate_modal_cost(), _object_schema(), parse_tool_calls(), ParsedToolCall, ParseResult, percentile(), prompt_manifest() (+17 more)

### Community 10 - "TaskSplit"
Cohesion: 0.15
Nodes (17): EpisodeRecord, InMemoryMemoryProvider, MemoryProvider, RetrievalRequest, Surprising Connections (you probably didn't know these), Contracts Agent 1 must implement or integrate, FrozenEvalMemory, _first() (+9 more)

### Community 11 - "evolution.py"
Cohesion: 0.15
Nodes (21): contender_genome(), test_checkpoint_resume_is_idempotent_and_hash_stable(), test_killed_agents_cannot_reproduce_and_survivors_are_elites(), test_mutations_stay_in_ranges_and_parent_references_exist(), test_seeded_population_selection_and_hashes_are_stable(), breed_generation(), DeterministicMutationProposer, GenerationCheckpoint (+13 more)

### Community 12 - "test_world_model_generation.py"
Cohesion: 0.10
Nodes (23): ScriptedModelAdapter, episode_from_trace(), InMemoryTraceRepository, poisoned(), run(), test_interrupt_and_resume_is_idempotent_and_matches_uninterrupted(), test_memory_context_excludes_protected_killed_and_unscored_traces_and_reaches_the_prompt(), test_model_backed_generation_completes_with_identifiers_and_no_duplicates() (+15 more)

### Community 13 - "json"
Cohesion: 0.11
Nodes (21): main(), main(), fresh(), out(), test_corrupted_checkpoints_are_rejected(), test_finalize_refuses_incomplete_generation(), test_hash_covers_content_so_encode_is_deterministic(), test_incompatible_versions_are_rejected() (+13 more)

### Community 14 - "snapshot.py"
Cohesion: 0.19
Nodes (10): coverage(), meta_url(), parse_price(), review_url(), build(), source_revision(), stream_jsonl(), main() (+2 more)

### Community 15 - "test_catalog_snapshot.py"
Cohesion: 0.24
Nodes (8): meta(), rev(), run(), test_deterministic_hash(), test_identical_source_reviews_get_distinct_canonical_ids_and_keep_the_original(), test_keeps_only_priced_products_with_enough_real_reviews(), test_per_product_cap_and_provenance(), test_stream_jsonl_drops_partial_last_line()

### Community 16 - "agents/runner.py"
Cohesion: 0.09
Nodes (10): EpisodeTermination, ActionPolicy, ModelStep, run_episode(), RunnerConfig, InvalidActionOrder, GuardViolation, calculate_efficiency_penalty() (+2 more)

### Community 17 - "create_app"
Cohesion: 0.08
Nodes (33): create_app(), confirm(), get_buyer(), get_payments(), get_router(), __getattr__(), _guard(), _http() (+25 more)

### Community 18 - "world.py"
Cohesion: 0.07
Nodes (39): to_agent_run_result(), AgentRunner, AgentRunRequest, AgentRunResult, _detail(), DocumentOut, _episode(), EpisodeDetail (+31 more)

### Community 19 - "indexing.py"
Cohesion: 0.17
Nodes (12): join(), legacy_to_canonical(), product_doc(), record_sha256(), review_doc(), review_id(), sample_stats(), source_review_key() (+4 more)

### Community 20 - "_http.py"
Cohesion: 0.14
Nodes (5): HttpError, _num(), request_json(), counting(), test_decimal_price_filters_serialize_on_the_wire()

### Community 21 - "pytest"
Cohesion: 0.14
Nodes (20): _Catalog, _resp(), Rig, _sandbox(), test_budget_rejected_before_any_api_call(), test_error_mapping_capture_before_approval_and_unknown_order(), test_inexact_or_nonpositive_amount_rejected(), test_no_capture_call_without_explicit_confirmation() (+12 more)

### Community 22 - "GenerationStore"
Cohesion: 0.13
Nodes (16): _job(), run_remote(), scheduled_resume(), status_remote(), _store(), put(), test_cost_is_wall_time_times_list_price(), test_status_lists_every_generation_and_flags_corruption_and_scheduler_resumes_only_unfinished() (+8 more)

### Community 23 - "main.py"
Cohesion: 0.17
Nodes (8): configure_logging(), ConfirmRequest, ConfirmResponse, ErrorBody, ErrorResponse, ProposeRequest, ProposeResponse, ProviderStatus

### Community 24 - "ScriptUnavailable"
Cohesion: 0.29
Nodes (4): _over_budget(), ScriptUnavailable, _surface(), _tokens()

### Community 25 - "GuardedPayments"
Cohesion: 0.11
Nodes (10): BuyerAgent, fail(), BuyerOutcome, AdapterPolicy, ModelAdapter, GuardedPayments, PendingOrder, executor() (+2 more)

### Community 26 - "test_api_world.py"
Cohesion: 0.11
Nodes (6): InMemoryReader, Snap, client(), test_agent_run_contract_and_unconfigured_model_is_a_clear_503(), test_world_endpoints_without_elastic_config_return_503_not_a_stack_trace(), traces()

### Community 27 - "MockPayments"
Cohesion: 0.08
Nodes (13): 2. Orders v2 (`payments/sandbox.py`), Capture, AmountMismatch, OrderNotApproved, OrderNotFound, PaymentDeclined, PaymentError, MockPayments (+5 more)

### Community 28 - "day1_probe.py"
Cohesion: 0.17
Nodes (9): checkpoint_resume_probe(), checkpoint_steps(), _download_model(), inspect_checkpoint(), run_tool_call_probe(), _sanitize(), _state_path(), tool_call_probe() (+1 more)

### Community 29 - "pathlib"
Cohesion: 0.08
Nodes (34): adapter_content_hash(), AdapterFile, AdapterSelection, ArtifactError, ArtifactManifest, compute_manifest_hash(), _Frozen, hash_adapter_dir() (+26 more)

### Community 30 - "SnapshotMismatch"
Cohesion: 0.12
Nodes (13): IncompleteReviewIds, SnapshotMismatch, _product(), FakeEs, prod(), provider(), rev(), test_amazon_products_never_expose_stock_or_size_even_if_a_doc_carries_it() (+5 more)

### Community 31 - "day1_live.py"
Cohesion: 0.15
Nodes (13): build_filters(), Channel3Provider, to_product(), 4. Required skills and dev tooling, channel3(), has_key(), load_env(), main() (+5 more)

### Community 32 - "ProviderRouter"
Cohesion: 0.08
Nodes (18): _RouterCatalog, load_config(), ProductResult, ProviderRouter, ProviderUnavailable, ReviewsResult, Routed, SearchResult (+10 more)

### Community 33 - "SandboxPayments"
Cohesion: 0.13
Nodes (7): 6. Hardening on `feat/paypal-live-checkout` (offline-verified; fake Orders v2, not PayPal), money(), SandboxPayments, test_money_formats_two_decimals_never_float(), test_approval_link_is_on_the_sandbox_host_and_creation_is_not_approval(), test_capture_before_approval_is_rejected_and_nothing_is_captured(), test_create_is_idempotent_and_exact_amount()

### Community 34 - "test_api_endpoints.py"
Cohesion: 0.24
Nodes (13): client(), test_capture_needs_explicit_confirmation_then_approval(), test_confirm_after_approval_captures_exact_amount(), test_over_budget_rejected_before_order(), test_price_mismatch_rejected(), test_propose_labels_the_quote_basis_and_never_claims_all_in_for_item_price(), test_provider_status_shows_bestbuy_disabled(), test_require_all_in_env_blocks_item_price_only_checkout() (+5 more)

### Community 35 - "run_generation.py"
Cohesion: 0.11
Nodes (21): default_router(), ElasticCatalogProvider, endpoint_from_cloud_id(), Elastic Serverless (live), tasks_hash(), load_audited_taskset(), main(), provider() (+13 more)

### Community 36 - "test_kernel_approver.py"
Cohesion: 0.10
Nodes (24): ApprovalBlocked, ApprovalNotAuthorized, check_approval_url(), KernelApprover, KernelError, approver(), authorized(), FakeBackend (+16 more)

### Community 37 - "Communities (81 total, 23 thin omitted)"
Cohesion: 0.03
Nodes (59): Communities (81 total, 23 thin omitted), Community 0 - "TaskSpec", Community 10 - "TaskSplit", Community 11 - "evolution.py", Community 12 - "test_world_runtime.py", Community 13 - "store.py", Community 14 - "day1_coverage.py", Community 15 - "snapshot.py" (+51 more)

### Community 38 - "types.ts"
Cohesion: 0.06
Nodes (53): Environment-variable inventory, Web app, @testing-library/react, zod, Local setup, HomePage(), sample(), emptyCheckpoints (+45 more)

### Community 39 - "God Nodes (most connected - your core abstractions)"
Cohesion: 0.09
Nodes (15): Community Hubs (Navigation), Corpus Check, God Nodes (most connected - your core abstractions), Graph Freshness, Graph Report - Crucible-integration  (2026-10-31), Import Cycles, Knowledge Gaps, Suggested Questions (+7 more)

### Community 40 - "test_eval_runner.py"
Cohesion: 0.08
Nodes (30): measured_docs(), PublicationRefused, to_markdown(), atomic_write(), EpisodeArtifact, EvaluationStore, finalize(), Incomplete (+22 more)

### Community 41 - "TraceRecord"
Cohesion: 0.08
Nodes (14): MemoryLeakage, similar_query(), eligible(), TraceRecord, TraceRepository, repo(), test_add_is_idempotent_per_episode(), test_elastic_query_carries_leakage_filter() (+6 more)

### Community 42 - "hashlib"
Cohesion: 0.12
Nodes (29): to_qwen_messages(), files(), curated(), rebuilt(), test_budget_numbers_and_sizes_are_not_mistaken_for_pii(), test_content_hash_helper_matches_what_curation_stores(), test_edited_record_content_no_longer_matches_manifest(), test_examples_use_the_inference_message_format_and_drop_synthesized_final_answer() (+21 more)

### Community 43 - "judge.py"
Cohesion: 0.14
Nodes (14): Scoring, ConfiguredJudgeAdapter, DeterministicFakeJudge, input_hash(), Judge, JudgeInvocation, JudgeResult, SemanticJudgeOutput (+6 more)

### Community 44 - "runtime.py"
Cohesion: 0.12
Nodes (13): system_prompt(), execute(), policy_factory(), test_unknown_or_fixture_prompt_variants_fail_closed(), compat_for(), episode_seed(), make_clock(), model_policy_factory() (+5 more)

### Community 45 - "test_training_torch_backend.py"
Cohesion: 0.06
Nodes (18): Qwen, TransformersEngine, backend_factory(), model(), run(), shard(), test_adapter_artifact_is_adapter_only(), test_cpu_refused_for_quantized_or_large_models() (+10 more)

### Community 46 - "InferenceError"
Cohesion: 0.07
Nodes (21): InferenceError, QwenInferenceResponse, modal_transport(), cancel(), ModalQwenClient, qwen_tools(), require_launch_authorization(), Transport (+13 more)

### Community 48 - "api/buyer.py"
Cohesion: 0.08
Nodes (29): AgentRunFailed, approval_event(), Assumptions, buyer_router(), BuyerRun, BuyerRunRequest, BuyerService, Comparison (+21 more)

### Community 49 - "os"
Cohesion: 0.10
Nodes (15): Training design, canonical_bytes(), sha256_file(), atomic_write_bytes(), CheckpointBackend, CheckpointMeta, CheckpointStore, _Frozen (+7 more)

### Community 51 - "test_eval_manifest.py"
Cohesion: 0.09
Nodes (21): Interface expected from / assumed about Agent 1, AdapterReference, ContenderConfig, ContenderError, load_adapter_reference(), sha256_file(), standard_contenders(), _Strict (+13 more)

### Community 52 - "Architecture"
Cohesion: 0.22
Nodes (9): Architecture, Catalog provider selection, Checkout, Data model, Deployment topology, Evolution loop, One episode, System context (+1 more)

### Community 53 - "Spike: PayPal sandbox checkout + Agent Toolkit + Kernel approval (Day-1 checks 1–3)"
Cohesion: 0.25
Nodes (8): 1. OAuth (verified live), 3. Contract tests, 4. PayPal Agent Toolkit / MCP (check 2), 5. Kernel buyer approval (check 1a), 7. The canonical live command, 8. Live results, 2026-11-02 (sandbox, $1.00 USD, 8 of 8 authorized runs used), Blockers, Spike: PayPal sandbox checkout + Agent Toolkit + Kernel approval (Day-1 checks 1–3)

### Community 54 - "PaymentsBackend"
Cohesion: 0.25
Nodes (4): reviews(), PaymentsBackend, 7.1 How each integration works (implementation detail), 7. Infrastructure: every service, what it does, and exactly how we use it

### Community 55 - "test_eval_publish.py"
Cohesion: 0.08
Nodes (16): ElasticReader, _key(), _match(), checkpoint_doc(), evaluation_docs(), EvaluationContext, publish(), main() (+8 more)

### Community 56 - "Generation gen-20261101-p8-t12"
Cohesion: 0.22
Nodes (8): Episodes, Fitness, Generation gen-20261101-p8-t12, Kills, Loophole Hunter (proposals only, none enabled), Safety, Tasks, Training curation

### Community 57 - "test_api_sandbox.py"
Cohesion: 0.13
Nodes (13): default_backend(), _launch_authorized(), captures(), sandbox_client(), test_cors_is_off_by_default_and_allows_only_listed_origins(), test_default_backend_uses_paypal_return_and_cancel_urls_from_env(), test_ledger_serves_real_sandbox_calls_sanitized_and_read_only(), test_model_backend_needs_qwen_env_and_modal_gates_else_typed_503() (+5 more)

### Community 58 - "webshop.py"
Cohesion: 0.09
Nodes (23): aggregate(), blocked(), check_setup(), EpisodeResult, _git_head(), Observation, parse_sessions(), run_episode() (+15 more)

### Community 60 - "Decisions"
Cohesion: 0.15
Nodes (13): 2026-10-30 Day-1 check 4b/8 (partial): Amazon Reviews 2023 coverage, 2026-10-30 scaffold, 2026-10-31 integration owner (agent 1): operational world, 2026-10-31 integration owner: security, skills, Astropods (Day-1 checks 9, 10), 2026-10-31 platform owner (agent 1): Day-1 provider and infrastructure decisions, 2026-11-03 release-final (agent A), Astropods (check 9) — from docs.astropods.com, Day-1 kill-checks (spec 15): NOT RUN (+5 more)

### Community 61 - "test_api_buyer.py"
Cohesion: 0.11
Nodes (35): Broken, build(), captures(), Clock, pending_id(), sandbox_build(), start(), start_fresh() (+27 more)

### Community 62 - "Platform status (agent 1) — branch `feat/platform-m1-m3`"
Cohesion: 0.29
Nodes (6): Blockers needing the user, Decisions awaiting integration, Environment names, External calls and approximate cost, Platform status (agent 1) — branch `feat/platform-m1-m3`, Requested from agent 2 (documented only; nothing edited in their dirs)

### Community 63 - "Runtime / integration status (Agent 1) — branch `feat/operational-world`"
Cohesion: 0.20
Nodes (9): API contracts for the web app (Agent 2), Environment names, External calls and cost (this branch), Findings for Agent 2, Phase log, Remaining blockers / risks, Reproduce, Runtime / integration status (Agent 1) — branch `feat/operational-world` (+1 more)

### Community 64 - "Deployment foundation"
Cohesion: 0.40
Nodes (5): Commands, Deployment foundation, Observability, Render runbook (free plan; the `render` CLI is not installed here, so this is manual), Services

### Community 65 - "StatusBadge"
Cohesion: 0.21
Nodes (32): NotFound(), GenerationsPage(), EpisodeDetailView(), Value(), EvaluationCard(), metrics, MetricView, ModelDashboard() (+24 more)

### Community 66 - "README.md"
Cohesion: 0.21
Nodes (3): eval-20261110-base — PLANNED, NOT RUN, Training dry run, Qwen bounded probe: blocked_not_run

### Community 67 - "episode-grid.tsx"
Cohesion: 0.08
Nodes (27): ag-grid-community, ag-grid-react, next, react, nextConfig, EpisodesPage(), metadata, RootLayout() (+19 more)

### Community 68 - "sys"
Cohesion: 0.22
Nodes (7): schedule_of(), test_schedule_is_off_by_default_and_on_only_with_the_explicit_flag(), live_ready(), run(), test_kernel_e2e_also_needs_the_browser_authorization(), test_live_tests_skip_without_credentials_or_outside_sandbox(), test_refuses_without_confirmation_and_without_sandbox()

### Community 73 - "planning.py"
Cohesion: 0.10
Nodes (32): TrainingApproval, code(), plan(), test_approval_is_bound_to_the_exact_training_manifest(), test_approved_ceiling_caps_a_larger_plan_request_only_by_rejecting_it(), test_budget_seconds_never_buy_more_than_the_ceiling(), test_ceiling_must_be_a_positive_finite_number(), test_each_gate_is_individually_required() (+24 more)

### Community 81 - "scoring.py"
Cohesion: 0.16
Nodes (28): Recommendation, RecommendationOutcome, ToolCall, ToolName, grounded_trace(), replace_trace(), rule_ids(), test_grounded_research_trace_survives_initial_rules() (+20 more)

### Community 82 - "test_training_service.py"
Cohesion: 0.12
Nodes (17): train(), _Frozen, TrainRequest, TrainResponse, request(), run(), test_container_rechecks_pins_gpu_manifest_and_ceiling_even_if_caller_lied(), test_pause_then_resume_through_the_service_and_idempotent_rerun() (+9 more)

### Community 83 - "TaskSpec"
Cohesion: 0.13
Nodes (19): CatalogProvider, FrozenCatalogProvider, _budget_violation(), _catalog_reviews(), _duplicate_payment(), _fabricated_review_evidence(), _hallucinated_product(), _insufficient_research() (+11 more)

### Community 84 - "audit"
Cohesion: 0.10
Nodes (17): load_manifest_hashes(), audit(), AuditReport, CheckResult, normalize(), _not_run(), products_of(), _result() (+9 more)

### Community 85 - "agent-workspace.tsx"
Cohesion: 0.11
Nodes (25): lucide-react, @testing-library/user-event, AgentWorkspace(), run(), first(), mergeRun(), amount(), checkoutErrorMessage() (+17 more)

### Community 86 - "ErrorState"
Cohesion: 0.15
Nodes (22): EpisodePage(), GlobalError(), Loading(), dynamic, ModelsPage(), dynamic, PaymentsPage(), dynamic (+14 more)

### Community 87 - "QwenModelAdapter"
Cohesion: 0.14
Nodes (21): MalformedModelOutput, _native_calls(), QwenModelAdapter, block(), Client, parse_arguments(), test_qwen_adapter_fails_closed_without_leaking_raw_output(), test_qwen_adapter_parses_native_calls_and_records_only_raw_hash() (+13 more)

### Community 88 - "train_lora.py"
Cohesion: 0.14
Nodes (20): launch_commands(), load_records(), main(), modal_train_transport(), _write(), argv(), clear_env(), fake_transport() (+12 more)

### Community 89 - "batch.py"
Cohesion: 0.14
Nodes (18): Split-leakage finding (the "5 protected-split overlaps"), build_eval_taskset(), trap_plans(), BatchConfig, BatchManifest, _eligible_trap(), _exact_labels(), generate_batch() (+10 more)

### Community 90 - "manifest.json"
Cohesion: 0.06
Nodes (30): catalog_hash, contenders, created_at, evaluation_id, manifest_version, memory_pool_hash, memory_pool_size, pass_k (+22 more)

### Community 91 - "test_eval_leakage.py"
Cohesion: 0.11
Nodes (16): dedupe_protected(), partition(), write_tasks(), main(), BigSynthetic, batch(), catalog(), test_catalog_manifest_mismatch_is_detected() (+8 more)

### Community 92 - "review_signals.py"
Cohesion: 0.20
Nodes (18): _content_hash(), extract_lexical_signals(), ExtractionResult, LexicalRule, _normalize(), record_human_review(), validate_signal_text(), ConstraintOperator (+10 more)

### Community 93 - "qwen_probe.py"
Cohesion: 0.15
Nodes (17): action_tools(), Message, ModelContract, ModelOutput, ModelRequest, ToolDefinition, ModelWebShopAgent, authorization_state() (+9 more)

### Community 94 - "tasks/schemas.py"
Cohesion: 0.11
Nodes (11): Invariants, Ambiguity, AttributeConstraint, ConstraintEvidence, ContractModel, Difficulty, ResearchRequirements, task() (+3 more)

### Community 95 - "test_qwen_adapter_inference.py"
Cohesion: 0.17
Nodes (19): base_request(), client_for(), make_artifact(), mreq(), test_adapter_client_label_must_be_its_checkpoint_id(), test_adapter_client_returns_adapter_checkpoint_identity_and_adapter_cost(), test_adapter_load_failure_is_a_rejection_not_a_base_answer_and_leaks_no_message(), test_adapter_request_runs_the_verified_adapter_and_reports_its_identity() (+11 more)

### Community 96 - "test_training_checkpoints.py"
Cohesion: 0.14
Nodes (9): test_adapter_trained_on_another_base_or_manifest_is_rejected(), test_artifact_ref_is_content_addressed_and_round_trips(), test_manifest_files_are_verified_on_load(), test_scripted_and_unknown_labels_are_refused_never_substituted_with_base(), two(), artifact_ref(), CheckpointCatalog, CheckpointError (+1 more)

### Community 97 - "PaymentLedger"
Cohesion: 0.11
Nodes (13): Platform wiring (release-final), Contracts (all additive), Handoff: PayPal live checkout (`feat/paypal-live-checkout`), Requests for others, Run the live check (needs the user's go-ahead), Safety properties and where they are tested, What is true now, Frontend-facing API changes (+5 more)

### Community 98 - "test_payments_guards.py"
Cohesion: 0.16
Nodes (17): Contracts agent 2 can consume (no Elastic import needed), Action order, Why PayPal is central, BudgetViolation, _ms(), NotConfirmed, OutOfStock, PriceMismatch (+9 more)

### Community 99 - "CrucibleApi"
Cohesion: 0.18
Nodes (4): CrucibleApi, withQuery(), pageSchema(), DataMode

### Community 100 - "Product"
Cohesion: 0.16
Nodes (13): Product, assign_split(), build_task_from_products(), catalog_manifest_hash(), FeasibilityResult, implied_needs_fit(), _matches(), select_best_value() (+5 more)

### Community 101 - "test_tasks_batch.py"
Cohesion: 0.12
Nodes (11): DifficultyMix, LeakageGuard, config(), FrozenFixture, make(), test_batch_hits_configured_ratio_and_difficulty_exactly(), test_configuration_rejects_ratios_outside_required_band(), test_held_out_category_is_isolated_and_manifested() (+3 more)

### Community 102 - "test_training_trainer.py"
Cohesion: 0.16
Nodes (15): go(), identity(), make_store(), StatefulBackend, test_changed_base_revision_or_data_refuses_to_resume(), test_corrupt_checkpoint_on_resume_falls_back_and_still_matches(), test_cost_is_known_only_when_rates_are_supplied_and_is_measured_not_estimated(), test_finished_run_is_idempotent_and_executes_no_steps() (+7 more)

### Community 103 - "package.json"
Cohesion: 0.09
Nodes (20): eslint, eslint-config-next, jsdom, postcss, prettier, react-dom, tailwindcss, @tailwindcss/postcss (+12 more)

### Community 104 - "eval/publish.py"
Cohesion: 0.15
Nodes (8): build_manifest(), EvaluationManifest, ManifestTask, Resumability, _Strict, Versions, _digest(), task_set_hash()

### Community 105 - "run_evaluation.py"
Cohesion: 0.22
Nodes (15): RunStatus, pool_hash(), write_report(), load_tasks(), load(), _catalog(), _client(), cmd_plan() (+7 more)

### Community 106 - "test_training_resume.py"
Cohesion: 0.20
Nodes (16): FileBackend, identity(), save(), store(), test_checkpoint_from_another_identity_is_incompatible_not_corrupt(), test_corrupt_latest_is_skipped_and_recorded_not_used(), test_crashed_save_leaves_only_a_temp_dir_that_prune_removes(), capture() (+8 more)

### Community 107 - "test_qwen_probe.py"
Cohesion: 0.16
Nodes (17): main(), write(), Client, probe_with(), test_adapter_probe_uses_the_adapter_checkpoint_and_records_its_identity(), factory(), test_artifact_is_deterministic_for_identical_inputs(), test_blocked_report_never_claims_a_pass() (+9 more)

### Community 108 - "compilerOptions"
Cohesion: 0.10
Nodes (20): compilerOptions, allowJs, esModuleInterop, incremental, isolatedModules, jsx, lib, module (+12 more)

### Community 109 - "SyntheticFrozen"
Cohesion: 0.14
Nodes (9): ElasticTraceRepository, audit(), main(), SyntheticFrozen, test_audit_flags_missing_and_duplicate_traces_and_passes_a_clean_generation(), test_resume_compatibility_includes_model_and_adapter_identity(), test_population_has_honest_agents_and_one_fixture_per_kill_rule(), world() (+1 more)

### Community 110 - "devDependencies"
Cohesion: 0.11
Nodes (19): devDependencies, eslint, eslint-config-next, jsdom, @playwright/test, postcss, prettier, tailwindcss (+11 more)

### Community 111 - "test_paypal_live_check.py"
Cohesion: 0.20
Nodes (14): authorize(), clean_env(), run(), test_challenge_is_exit_5_kernel_failure_7_paypal_failure_6_assertion_8(), blocked(), broken(), test_duplicate_capture_answered_2xx_but_one_capture_recorded_passes_and_is_reported(), test_duplicate_charge_is_caught_if_paypal_ever_recorded_a_second_capture() (+6 more)

### Community 112 - "check_submission.py"
Cohesion: 0.23
Nodes (8): check(), main(), placeholders(), sh(), env_values(), main(), scan(), test_scanner_finds_env_values_and_token_shapes_without_printing_them()

### Community 113 - "SubprocessWebShopEnv"
Cohesion: 0.19
Nodes (9): Blockers (exact), Commands, Measured evaluation (Agent 2) — branch `feat/measured-evaluation`, Metrics honesty changes (`eval/harness.py`), Not done / follow-ups, Status, WebShop, SubprocessWebShopEnv (+1 more)

### Community 114 - "eval/report.py"
Cohesion: 0.23
Nodes (8): Scripted shoppers, _successful(), build_report(), _metric(), NotAMeasurement, _num(), _percentile(), complete_artifacts()

### Community 115 - "verify"
Cohesion: 0.23
Nodes (10): check(), main(), ok(), verify(), bundle(), config(), episode(), gen() (+2 more)

### Community 116 - "test_modal_training_module.py"
Cohesion: 0.24
Nodes (7): load(), test_gpu_is_attached_only_when_explicitly_enabled(), test_inference_and_training_share_overlapping_pins(), test_pins_are_exact_and_cover_the_training_stack(), test_timeout_is_under_the_approved_forty_five_minutes_and_above_the_soft_stop(), test_every_module_imports_cleanly(), test_every_package_dir_is_declared_for_packaging()

### Community 117 - "Ponytail audit (repo-wide, 2026-11-03)"
Cohesion: 0.15
Nodes (3): Ponytail audit (repo-wide, 2026-11-03), Engine, TrainBackend

### Community 118 - "FakeEngine"
Cohesion: 0.17
Nodes (4): EngineOutput, InputTooLong, FakeEngine, rig()

### Community 119 - "generate-samples.mjs"
Cohesion: 0.17
Nodes (8): routes, files, fixtures, here, output, sourceRoot, webRoot, files()

### Community 120 - "Web product status — `feat/web-product`"
Cohesion: 0.17
Nodes (11): API contracts consumed, Branch commits, Buyer contract convergence, Data modes, Delivered routes, Deployment, Honest blockers, Remaining platform contracts (+3 more)

### Community 121 - "re"
Cohesion: 0.20
Nodes (4): test_every_script_parses(), test_no_live_hosts_and_no_embedded_credentials(), test_paypal_folder_covers_the_whole_flow_in_order(), walk()

### Community 122 - "test_verify_deploy.py"
Cohesion: 0.26
Nodes (8): run(), site(), test_empty_trace_store_fails_the_generation_check(), test_healthy_deployment_passes_every_check(), test_missing_cors_origin_fails(), test_model_path_must_be_typed_503_unless_a_model_is_configured(), test_secret_in_web_bundle_fails_without_printing_it(), test_unreachable_host_fails_cleanly()

### Community 123 - "scripts"
Cohesion: 0.17
Nodes (12): scripts, build, dev, format, format:check, generate:samples, lint, start (+4 more)

### Community 124 - "world/report.py"
Cohesion: 0.26
Nodes (8): _killed_by(), model_usage(), _quality(), _rate(), rates(), summarize(), to_markdown(), write()

### Community 125 - "Crucible: Devpost text"
Cohesion: 0.18
Nodes (11): Accomplishments, Built with, Challenges, Crucible: Devpost text, How we built it, Significantly updated during the submission period, Testing instructions, What it does (+3 more)

### Community 126 - "QwenInferenceClient"
Cohesion: 0.20
Nodes (5): QwenInferenceClient, Status: built / live-verified / blocked / unimplemented, 2026-11-02/03 Phase 1, 2026-11-03 Phase 2 (deploy readiness), Release-final status (Agent A, platform)

### Community 127 - "Modal inference + resumable LoRA training (Agent 1) — branch `feat/modal-training-runtime`"
Cohesion: 0.20
Nodes (7): Authorization blockers (exact), Contracts (stable; Agent 2 / integrator rely on these), Known risks / not verified, Live run (only after the human sets the variables; do not run otherwise), Modal inference + resumable LoRA training (Agent 1) — branch `feat/modal-training-runtime`, Status, Tests (exact)

### Community 128 - "Day-1 checks 5–6: Qwen tool calling and Modal resumability"
Cohesion: 0.20
Nodes (9): Checkpoint/resume evidence, Day-1 checks 5–6: Qwen tool calling and Modal resumability, GPU choice, cost, and LoRA estimate, Model and license verification, Outcome, Recommendation and blocker, Reproduction, Seeded prompt suite and metrics (+1 more)

### Community 129 - "test_check_submission.py"
Cohesion: 0.42
Nodes (7): repo(), run(), test_any_placeholder_fails_in_readme_or_submission_docs(), test_clean_repo_with_expected_tags_passes(), test_license_and_visibility_come_from_gh_and_failure_to_ask_fails_closed(), test_missing_due_tag_fails_but_future_tags_are_not_required(), test_tracked_env_file_and_secret_shapes_and_bad_json_fail()

### Community 130 - "day1_coverage.py"
Cohesion: 0.36
Nodes (6): iter_jsonl(), attr_probe(), main(), seg_text(), size_of(), windows()

### Community 131 - "Generation fixture-rc-91"
Cohesion: 0.22
Nodes (8): Episodes, Fitness, Generation fixture-rc-91, Kills, Loophole Hunter (proposals only, none enabled), Safety, Tasks, Training curation

### Community 132 - "Qwen serving options through December 15"
Cohesion: 0.25
Nodes (7): Cost model (list-rate scenarios, not measured spend), Decision checklist, Degraded behavior, Fixed deployment facts, Options for the user, Qwen serving options through December 15, Required abuse and spend guardrails

### Community 133 - "Generation rc-real-20261102"
Cohesion: 0.25
Nodes (8): Episodes, Fitness, Generation rc-real-20261102, Kills, Loophole Hunter (proposals only, none enabled), Safety, Tasks, Training curation

### Community 134 - "Deterministic core engine"
Cohesion: 0.25
Nodes (7): Deterministic core engine, Evaluation, Evolution and resume, Fixture limitations, Initial kill registry, Leakage and curation, Task computation

### Community 135 - "dependencies"
Cohesion: 0.25
Nodes (8): dependencies, ag-grid-community, ag-grid-react, lucide-react, next, react, react-dom, zod

### Community 136 - "Release convergence (Agent 1) — branch `feat/release-convergence`"
Cohesion: 0.29
Nodes (7): External spend, Operational run metrics (pipeline evidence, NOT model performance — scripted shoppers read the reference answer), Qwen probe — not measured, Release convergence (Agent 1) — branch `feat/release-convergence`, Remaining blockers, Reproduce, Tests (exact)

### Community 138 - "rehash_manifests.py"
Cohesion: 0.47
Nodes (3): snapshot_digest(), live_snapshots(), main()

### Community 139 - "Model pipeline integration status"
Cohesion: 0.33
Nodes (5): Live stages and blockers, Model pipeline integration status, Offline integration, Reproduction, Verification

### Community 140 - ".prettierrc.json"
Cohesion: 0.40
Nodes (4): printWidth, semi, singleQuote, trailingComma

### Community 141 - "Crucible web product"
Cohesion: 0.40
Nodes (4): Crucible web product, Live API prerequisites, Routes, Verification

### Community 142 - "Platform Day-1 findings (agent 1)"
Cohesion: 0.50
Nodes (4): Channel3 (live, 16 calls / 12 credits), Decisions taken, Platform Day-1 findings (agent 1), Scorecard

### Community 143 - "Demo video script (target 2:40, hard limit under 3:00)"
Cohesion: 0.50
Nodes (3): Alternative block B2 (only if the model endpoint is enabled: `<<LIVE_API_URL>>/ready` shows `model_configured: true`), Demo video script (target 2:40, hard limit under 3:00), Recordings the owner must capture (the assistant cannot record)

## Knowledge Gaps
- **12 isolated node(s):** `crucible`, `react-dom`, `@tailwindcss/postcss`, `@types/node`, `@types/react` (+7 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 1143 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **23 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Crucible` connect `datetime` to `README.md`, `world.py`, `types.ts`?**
  _High betweenness centrality (0.178) - this node is a cross-community bridge._
- **Are the 55 inferred relationships involving `TaskSpec` (e.g. with `AdapterPolicy` and `ActionPolicy`) actually correct?**
  _`TaskSpec` has 55 INFERRED edges - model-reasoned connections that need verification._
- **What connects `crucible`, `react-dom`, `@tailwindcss/postcss` to the rest of the system?**
  _12 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `decimal` be split into smaller, more focused modules?**
  _Cohesion score 0.0841799709724238 - nodes in this community are weakly interconnected._
- **Why does `GuardedPayments` connect `GuardedPayments` to `datetime`, `test_agent_model_adapter.py`, `TaskSplit`, `create_app`, `pytest`, `main.py`, `MockPayments`, `SandboxPayments`, `God Nodes (most connected - your core abstractions)`, `runtime.py`, `InferenceError`, `api/buyer.py`, `PaymentsBackend`, `test_api_buyer.py`, `Runtime / integration status (Agent 1) — branch `feat/operational-world``, `TaskSpec`, `PaymentLedger`, `test_payments_guards.py`, `Ponytail audit (repo-wide, 2026-11-03)`?**
  _High betweenness centrality (0.127) - this node is a cross-community bridge._
- **Are the 40 inferred relationships involving `Product` (e.g. with `render()` and `_stock()`) actually correct?**
  _`Product` has 40 INFERRED edges - model-reasoned connections that need verification._
- **Should `datetime` be split into smaller, more focused modules?**
  _Cohesion score 0.05477477477477478 - nodes in this community are weakly interconnected._