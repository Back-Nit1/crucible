# Graph Report - Crucible-platform  (2026-10-31)

## Corpus Check
- 69 files · ~50,122 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 5 file(s) not represented in the graph (top: (none) 3, .example 1, .lock 1)

## Summary
- 647 nodes · 1438 edges · 26 communities (16 shown, 10 thin omitted)
- Extraction: 90% EXTRACTED · 10% INFERRED · 0% AMBIGUOUS · INFERRED: 148 edges (avg confidence: 0.93)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `e9e97963`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- test_payments_contract.py
- providers/elastic.py
- json
- qwen_toolcalls.py
- Architecture
- pytest
- Build Spec: Crucible — an evolutionary RL world that trains open models to shop on PayPal
- decimal
- Product
- test_memory_retrieval.py
- create_app
- test_catalog_router.py
- Graph Report - Crucible   (2026-10-30)
- main.py
- ProviderRouter
- router.py
- test_api_endpoints.py
- FakePayPal
- crucible

## God Nodes (most connected - your core abstractions)
1. `create_app()` - 31 edges
2. `SandboxPayments` - 30 edges
3. `Product` - 29 edges
4. `MockPayments` - 27 edges
5. `Elastic` - 23 edges
6. `ProviderRouter` - 22 edges
7. `Build Spec: Crucible — an evolutionary RL world that trains open models to shop on PayPal` - 21 edges
8. `Channel3Provider` - 18 edges
9. `ElasticCatalogProvider` - 18 edges
10. `GuardedPayments` - 18 edges

## Surprising Connections (you probably didn't know these)
- `4. Required skills and dev tooling` --references--> `Channel3Provider`  [INFERRED]
  prompt.md → catalog/providers/channel3.py
- `Scorecard` --references--> `OrderNotApproved`  [INFERRED]
  docs/spikes/platform-day1.md → payments/errors.py
- `2026-10-30 scaffold` --references--> `PriceMismatch`  [INFERRED]
  DECISIONS.md → payments/guards.py
- `Contracts agent 2 can consume (no Elastic import needed)` --references--> `reviews()`  [INFERRED]
  docs/handoffs/platform-status.md → api/main.py
- `Elastic (offline-verified only)` --references--> `reviews()`  [INFERRED]
  docs/spikes/catalog-elastic.md → api/main.py

## Import Cycles
- None detected.

## Communities (26 total, 10 thin omitted)

### Community 0 - "test_payments_contract.py"
Cohesion: 0.05
Nodes (29): God Nodes (most connected - your core abstractions), Suggested Questions, 1. OAuth (verified live), 2. Orders v2 (`payments/sandbox.py`), 3. Contract tests, 4. PayPal Agent Toolkit / MCP (check 2), 6. Pending (blocked on buyer credentials), Blockers (+21 more)

### Community 1 - "providers/elastic.py"
Cohesion: 0.05
Nodes (37): default_router(), Elastic, ElasticCatalogProvider, endpoint_from_cloud_id(), hybrid_review_query(), mappings(), _product(), _vec() (+29 more)

### Community 2 - "json"
Cohesion: 0.07
Nodes (35): join(), product_doc(), review_doc(), review_id(), sample_stats(), coverage(), iter_jsonl(), meta_url() (+27 more)

### Community 3 - "qwen_toolcalls.py"
Cohesion: 0.07
Nodes (33): checkpoint_resume_probe(), checkpoint_steps(), _download_model(), inspect_checkpoint(), run_tool_call_probe(), _sanitize(), _state_path(), tool_call_probe() (+25 more)

### Community 4 - "Architecture"
Cohesion: 0.04
Nodes (40): 2026-10-30 Day-1 check 4b/8 (partial): Amazon Reviews 2023 coverage, 2026-10-30 scaffold, 2026-10-31 integration owner: security, skills, Astropods (Day-1 checks 9, 10), 2026-10-31 platform owner (agent 1): Day-1 provider and infrastructure decisions, Astropods (check 9) — from docs.astropods.com, Day-1 kill-checks (spec 15): NOT RUN, Decisions, Integration status (+32 more)

### Community 5 - "pytest"
Cohesion: 0.10
Nodes (24): CatalogProvider, Surprising Connections (you probably didn't know these), Contracts agent 2 can consume (no Elastic import needed), Tool contract, PaymentsBackend, BudgetViolation, GuardedPayments, GuardViolation (+16 more)

### Community 6 - "Build Spec: Crucible — an evolutionary RL world that trains open models to shop on PayPal"
Cohesion: 0.05
Nodes (42): 0. Ground rules for you (read first), 10.1 Design direction, 10.2 Shopping Chat (hero), 10.3 World Dashboard, 10.4 Model Dashboard, 10.5 Reference visuals (look, don't copy), 10.6 Docs and visuals we must produce, 10. Product surface and design direction (+34 more)

### Community 7 - "decimal"
Cohesion: 0.09
Nodes (9): 5. Kernel buyer approval (check 1a), ApprovalBlocked, KernelApprover, load(), FakeBackend, FakeKernel, test_approves_and_always_deletes_browser(), test_challenge_stops_run() (+1 more)

### Community 8 - "Product"
Cohesion: 0.12
Nodes (14): Product, Review, build_filters(), Channel3Provider, to_product(), _review(), channel3(), Snap (+6 more)

### Community 9 - "test_memory_retrieval.py"
Cohesion: 0.11
Nodes (14): similar_query(), eligible(), InMemoryTraceRepository, TraceRecord, TraceRepository, repo(), test_add_is_idempotent_per_episode(), test_elastic_query_carries_leakage_filter() (+6 more)

### Community 10 - "create_app"
Cohesion: 0.16
Nodes (18): create_app(), confirm(), get_payments(), get_router(), _guard(), _payment(), product(), propose() (+10 more)

### Community 11 - "test_catalog_router.py"
Cohesion: 0.18
Nodes (11): ProviderUnavailable, Fake, router(), test_bestbuy_disabled_cannot_be_routed(), test_live_falls_back_to_snapshot_and_says_so(), test_live_uses_channel3_not_labelled_snapshot(), test_missing_reviews_are_none_not_invented(), test_router_refilters_price_cap() (+3 more)

### Community 12 - "Graph Report - Crucible   (2026-10-30)"
Cohesion: 0.12
Nodes (16): Communities (17 total, 9 thin omitted), Community 0 - "CatalogProvider", Community 10 - "10. Product surface and design direction", Community 1 - "Architecture", Community 2 - "Build Spec: Crucible — an evolutionary RL world that trains open models to shop on PayPal", Community 3 - "guards.py", Community 4 - "test_payments_guards.py", Community 7 - "8. Component build specs" (+8 more)

### Community 13 - "main.py"
Cohesion: 0.17
Nodes (7): ConfirmRequest, ConfirmResponse, ErrorBody, ErrorResponse, ProposeRequest, ProposeResponse, ProviderStatus

### Community 15 - "router.py"
Cohesion: 0.20
Nodes (5): load_config(), ProductResult, ReviewsResult, Routed, SearchResult

### Community 16 - "test_api_endpoints.py"
Cohesion: 0.27
Nodes (11): client(), test_capture_needs_explicit_confirmation_then_approval(), test_confirm_after_approval_captures_exact_amount(), test_over_budget_rejected_before_order(), test_price_mismatch_rejected(), test_provider_status_shows_bestbuy_disabled(), test_reviews_and_missing_product(), test_search_labels_snapshot_and_source() (+3 more)

## Knowledge Gaps
- **1 isolated node(s):** `crucible`
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 247 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **10 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Build Spec: Crucible — an evolutionary RL world that trains open models to shop on PayPal` connect `Build Spec: Crucible — an evolutionary RL world that trains open models to shop on PayPal` to `create_app`, `Architecture`?**
  _High betweenness centrality (0.124) - this node is a cross-community bridge._
- **Are the 11 inferred relationships involving `create_app()` (e.g. with `ProductResult` and `ProviderRouter`) actually correct?**
  _`create_app()` has 11 INFERRED edges - model-reasoned connections that need verification._
- **What connects `crucible` to the rest of the system?**
  _1 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `test_payments_contract.py` be split into smaller, more focused modules?**
  _Cohesion score 0.053554040895813046 - nodes in this community are weakly interconnected._
- **Why does `Contracts agent 2 can consume (no Elastic import needed)` connect `pytest` to `test_payments_contract.py`, `providers/elastic.py`, `Architecture`, `Product`, `test_memory_retrieval.py`, `create_app`?**
  _High betweenness centrality (0.103) - this node is a cross-community bridge._
- **Are the 8 inferred relationships involving `SandboxPayments` (e.g. with `Contracts agent 2 can consume (no Elastic import needed)` and `3. Contract tests`) actually correct?**
  _`SandboxPayments` has 8 INFERRED edges - model-reasoned connections that need verification._
- **Should `providers/elastic.py` be split into smaller, more focused modules?**
  _Cohesion score 0.050078247261345854 - nodes in this community are weakly interconnected._