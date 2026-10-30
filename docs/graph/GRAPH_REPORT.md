# Graph Report - Crucible   (2026-10-30)

## Corpus Check
- 17 files · ~8,590 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 4 file(s) not represented in the graph (top: (none) 2, .example 1, .lock 1)

## Summary
- 139 nodes · 207 edges · 17 communities (8 shown, 9 thin omitted)
- Extraction: 92% EXTRACTED · 8% INFERRED · 0% AMBIGUOUS · INFERRED: 16 edges (avg confidence: 0.95)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `ea65e32b`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- CatalogProvider
- Architecture
- Build Spec: Crucible — an evolutionary RL world that trains open models to shop on PayPal
- guards.py
- test_payments_guards.py
- Capture
- 8. Component build specs
- 6. Architecture (mapped out)
- main.py
- 10. Product surface and design direction
- crucible

## God Nodes (most connected - your core abstractions)
1. `Build Spec: Crucible — an evolutionary RL world that trains open models to shop on PayPal` - 21 edges
2. `make()` - 10 edges
3. `8. Component build specs` - 10 edges
4. `CatalogProvider` - 9 edges
5. `Capture` - 9 edges
6. `PaymentsBackend` - 9 edges
7. `GuardedPayments` - 9 edges
8. `Architecture` - 9 edges
9. `MockPayments` - 8 edges
10. `6. Architecture (mapped out)` - 8 edges

## Surprising Connections (you probably didn't know these)
- `2026-10-30 scaffold` --references--> `PriceMismatch`  [INFERRED]
  DECISIONS.md → payments/guards.py
- `7.1 How each integration works (implementation detail)` --references--> `MockPayments`  [INFERRED]
  prompt.md → payments/mock.py
- `7.1 How each integration works (implementation detail)` --references--> `CatalogProvider`  [INFERRED]
  prompt.md → catalog/providers/base.py
- `7.1 How each integration works (implementation detail)` --references--> `PaymentsBackend`  [INFERRED]
  prompt.md → payments/base.py
- `test_budget_cap_enforced()` --uses--> `BudgetViolation`  [INFERRED]
  tests/test_payments_guards.py → payments/guards.py

## Import Cycles
- None detected.

## Communities (17 total, 9 thin omitted)

### Community 0 - "CatalogProvider"
Cohesion: 0.15
Nodes (8): CatalogProvider, Product, Review, PaymentsBackend, GuardedPayments, 7.1 How each integration works (implementation detail), 7. Infrastructure: every service, what it does, and exactly how we use it, FakeCatalog

### Community 1 - "Architecture"
Cohesion: 0.11
Nodes (15): 2026-10-30 scaffold, Day-1 kill-checks (spec 15): NOT RUN, Decisions, Tooling versions (2026-10-30), Architecture, Catalog provider selection, Checkout, Data model (+7 more)

### Community 2 - "Build Spec: Crucible — an evolutionary RL world that trains open models to shop on PayPal"
Cohesion: 0.12
Nodes (17): 0. Ground rules for you (read first), 11. Data terms and compliance, 12. Evaluation, 13. Repository layout, 14. Non-functional requirements, 15. Day-1 kill-checks (do these first; report results before building further), 16. Milestones (deadline Nov 12, 12:00 PM PT), 17. Definition of done (+9 more)

### Community 3 - "guards.py"
Cohesion: 0.21
Nodes (6): BudgetViolation, GuardViolation, idempotency_key(), NotConfirmed, OutOfStock, PendingOrder

### Community 4 - "test_payments_guards.py"
Cohesion: 0.51
Nodes (9): PriceMismatch, make(), propose(), test_budget_cap_enforced(), test_happy_path_charges_exact_listed_price(), test_idempotent_retries_single_charge(), test_requires_explicit_confirmation(), test_stale_price_rejected() (+1 more)

### Community 7 - "8. Component build specs"
Cohesion: 0.20
Nodes (10): 8.1 Catalog snapshot (`catalog/`), 8.2 Task generator (`tasks/`), 8.3 Agent tools (action space), 8.4 PayPal layer (`payments/`), 8.5 Population and evolution (`world/`), 8.6 Scoring (`scoring/`), 8.7 Loophole Hunter (`world/loophole_hunter.py`), 8.8 Trace store and memory (`memory/`) (+2 more)

### Community 8 - "6. Architecture (mapped out)"
Cohesion: 0.25
Nodes (8): 6.1 System context, 6.2 Catalog provider selection (fallback chain), 6.3 One episode (agent ↔ world), 6.4 Evolution loop, 6.5 Checkout (sandbox, no human click), 6.6 Training and evaluation pipeline, 6.7 Deployment topology, 6. Architecture (mapped out)

### Community 10 - "10. Product surface and design direction"
Cohesion: 0.29
Nodes (7): 10.1 Design direction, 10.2 Shopping Chat (hero), 10.3 World Dashboard, 10.4 Model Dashboard, 10.5 Reference visuals (look, don't copy), 10.6 Docs and visuals we must produce, 10. Product surface and design direction

## Knowledge Gaps
- **1 isolated node(s):** `crucible`
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 73 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **9 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Build Spec: Crucible — an evolutionary RL world that trains open models to shop on PayPal` connect `Build Spec: Crucible — an evolutionary RL world that trains open models to shop on PayPal` to `CatalogProvider`, `Architecture`, `8. Component build specs`, `6. Architecture (mapped out)`, `10. Product surface and design direction`?**
  _High betweenness centrality (0.485) - this node is a cross-community bridge._
- **Are the 2 inferred relationships involving `CatalogProvider` (e.g. with `GuardedPayments` and `7.1 How each integration works (implementation detail)`) actually correct?**
  _`CatalogProvider` has 2 INFERRED edges - model-reasoned connections that need verification._
- **What connects `crucible` to the rest of the system?**
  _1 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Architecture` be split into smaller, more focused modules?**
  _Cohesion score 0.10526315789473684 - nodes in this community are weakly interconnected._
- **Why does `7.1 How each integration works (implementation detail)` connect `CatalogProvider` to `Capture`?**
  _High betweenness centrality (0.334) - this node is a cross-community bridge._
- **Are the 2 inferred relationships involving `Capture` (e.g. with `GuardedPayments` and `MockPayments`) actually correct?**
  _`Capture` has 2 INFERRED edges - model-reasoned connections that need verification._
- **Should `Build Spec: Crucible — an evolutionary RL world that trains open models to shop on PayPal` be split into smaller, more focused modules?**
  _Cohesion score 0.11764705882352941 - nodes in this community are weakly interconnected._