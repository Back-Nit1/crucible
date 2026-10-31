# Decisions

Log every non-obvious choice, doc-vs-spec conflict, fallback, and Day-1 provider decision.

## Tooling versions (2026-10-30)
- git 2.39.5, Python 3.12.6, uv 0.11.21, node 22.22.3, pnpm 10.33.0, gh 2.100.0
- modal client 1.5.0, graphify 0.9.83
- Not yet verified: Ponytail plugin (skill loads), frontend-design / UI-UX skills, APIMatic PayPal plugin.

## 2026-10-30 scaffold
- Python via `uv`; deps limited to fastapi/uvicorn/pydantic/pyyaml until a component needs more.
- Money is `Decimal` everywhere; no floats near payments.
- Directories from spec section 13 are created when they get code, not up front.
- `prompt.md` stays at repo root as the source-of-truth spec.
- Guards check the *live catalog price* (not the agent's claim) for budget, so a stale or
  wrong expected_total cannot slip through. Unknown product on purchase = `PriceMismatch`.
- Idempotency: key = sha256(task|agent|product|variant)[:32]; backends must dedupe on it.

## Day-1 kill-checks (spec 15): NOT RUN
All 10 need real credentials or network access (PayPal sandbox, KERNEL, Channel3, Best Buy,
Elastic, Modal GPU, Astropods). Awaiting keys. Results go here and in `config/providers.yaml`.
- Graphify built via `graphify update .` (code-only, no LLM); report + graph copied to docs/graph/. Doc-semantic pass (`/graphify` skill) not run.

## 2026-10-30 Day-1 check 4b/8 (partial): Amazon Reviews 2023 coverage
Method: first 40 MB of each `meta_<Category>.jsonl` (prefix sample, may be biased by file order).
"usable" = numeric price AND `rating_number` >= 5. Review text not fetched yet.

| Category | products | price | >=5 reviews | usable |
|---|---|---|---|---|
| Video_Games | 11315 | 5989 | 9511 | 5467 |
| Sports_and_Outdoors | 13728 | 6610 | 10782 | 5896 |
| Electronics | 10869 | 4683 | 8449 | 4008 |
| Office_Products | 11723 | 6103 | 9165 | 5332 |
| Home_and_Kitchen | 10800 | 5627 | 8674 | 5005 |
| Clothing_Shoes_and_Jewelry | 13988 | 7602 | 11967 | 7202 |
| Software | 14196 | 2718 | 8455 | 1466 |
| Musical_Instruments | 12112 | 6126 | 8913 | 5174 |
| Books | 10725 | 9705 | 8453 | 7655 |

Findings:
- ~40-50% of products have price + enough reviews (Software is weak on price: drop from tasks).
- **No stock or per-size availability in the meta schema** (fields: title, price, features,
  description, details, categories, store, average_rating, rating_number, parent_asin...).
  `details['Size']` appeared on ~248 of ~14k Clothing prefix records. Spec's "size 12 in stock"
  hard constraint therefore cannot come from this dataset. Needs a decision: drop size/stock
  constraints for training tasks, or synthesize a deterministic stock/size snapshot (must be
  disclosed; never presented as real Amazon stock). Not decided; blocks task generator.
- Review files are 1.5-31 GB per category (`review_categories/<Cat>.jsonl`), joined on
  `parent_asin`. Full-file streaming filter needed per category; Video_Games 2.7 GB and
  Musical_Instruments 1.6 GB are the cheapest. Not downloaded yet.
- Caveat: my first shoe-attribute probe filtered on a substring that matched every record, so
  its attribute counts are unreliable; rerun with a proper category filter.
- License: dataset page states none; cite Hou et al. 2024 (arXiv:2403.03952), research use.

## 2026-10-31 integration owner: security, skills, Astropods (Day-1 checks 9, 10)

### Secret hygiene
- `.env` exists and is ignored (`.gitignore:1`). `.env.example` restored to its committed blank state plus blank `PAYPAL_SANDBOX_BUYER_EMAIL=` / `PAYPAL_SANDBOX_BUYER_PASSWORD=`. The real `.env` has no buyer keys yet.
- Scan (values from `.env` matched against all tracked files, `git log --all -p`, and token-shaped patterns): **0 hits**. No `.env` file was ever committed; no remote is configured, so nothing was pushed.
- Finding: 4 **unreachable (dangling) blobs** in the local object store contain real values from the modified `.env.example` (KERNEL, Modal, Elastic, Zapier keys). They are not in any commit or ref and never left this machine. Not pruned yet (needs user approval: `git gc --prune=now`). Rotate Modal (in progress); consider rotating KERNEL, Elastic, Zapier too.
- Modal is not used until authentication with the replacement token succeeds.

### Skills (check 10)
| Item | Status | Evidence |
|---|---|---|
| Ponytail | OK | skill `ponytail` loads; `ponytail-review`/`-audit` listed |
| frontend-design | OK | `frontend-design@claude-code-plugins` installed; `anthropic-frontend-design` skill present |
| UI/UX skill | OK, name is `uiux-pro-max` (also `uiux-design`, `uiux-design-system`, `uiux-styling`) | `~/.claude/skills/` |
| Graphify | OK | CLI 0.9.83; `docs/graph/` committed. Doc-semantic pass still not run |
| APIMatic PayPal context | **NOT INSTALLED** | not in `installed_plugins.json`. Per the apimatic/context-matic README: `/plugin marketplace add apimatic/context-matic`, `/plugin install context-matic@apimatic-context-matic`, `/reload-plugins`, `/mcp`; needs Claude Code >= 2.1.92. Covers "PayPal Server SDK" (orders, payments, vault); the README does not name a "PayPal REST API" entry. Interactive install, user must run it. |

### Astropods (check 9) — from docs.astropods.com
- Available: hosted platform, `ast` CLI. Availability tier (GA/beta/waitlist) not stated in docs.
- Auth: `ast login` = device flow (short code + URL, `--no-browser` supported); account required (signup at astropods.com/signup). Tokens in keyring or `~/.ast/credentials.json`. `ast whoami` verifies. No API-key flow documented.
- Free tier: **not stated**. Docs say a new personal account gets "one-time credits to spend before it needs a card"; usage limits page has pay-as-you-go spend caps that hard-stop all agents. Pricing not documented.
- Deploy: `ast spec validate` -> `ast blueprint push` -> `ast blueprint deploy` -> `ast agent list`. A blueprint = built container images + registered spec.
- Fit: a Python custom adapter exists (`pip install astropods-adapter-core`, Python >= 3.10, `agent.interfaces.messaging: true`), so deploying our agent is plausible but means wrapping it in Astropods' messaging adapter, not just pointing at the Render FastAPI. Telemetry from an agent hosted elsewhere is **not** supported: external telemetry accepts only official integrations (Claude Code listed). Docs do not say if arbitrary container images are accepted.
- Decision (provisional): treat Astropods as optional and cut-order item (spec 16). Day-1 verdict **blocked** until the user runs `ast login` and a trivial blueprint deploy succeeds. Fallback stays Render + own Elastic traces.

### Integration status
- PayPal/Kernel, catalog/Elastic, Modal/Qwen worktrees were still at `8f8b822` with no changes when checked; no reports to integrate. Day-1 checks 1-8 remain NOT RUN.
- A separate session is working on `feat/scoring-contracts` in the primary worktree (task/scoring contracts). Not merged; not reviewed.

## 2026-10-31 platform owner (agent 1): Day-1 provider and infrastructure decisions
Evidence: `docs/spikes/platform-day1.md`. Config: `config/providers.yaml`.
- **Training/eval catalog = Elastic snapshot of Amazon Reviews 2023, always.** Channel3 snapshot/training rejected: ToS s.7 (per earlier doc review; a human should confirm the clause text).
- **Live chat default = Elastic snapshot, labelled `snapshot` in every API response.** Channel3 works for live display (live probe: offers, in-stock, structured attributes on all 11 probe categories) but returns **no review text**, so it cannot give review-grounded picks, and spec 6.2 gates it on storage terms which fail. Enable by setting `live_chat: channel3` (falls back to the snapshot on error, visibly via `fallback_from`). **Open question for the user.**
- **Best Buy disabled** (signup unavailable); the router removes disabled providers.
- Channel3 `max_price` filter is unreliable (results with offers over the cap): the router re-filters; payment guards re-check the live price.
- Channel3 variant `available` is empty in search and populated only on product detail.
- **Embeddings: `.jina-embeddings-v5-text-nano` (768d, EIS-hosted, <=16 inputs/request).** The documented-default `.multilingual-e5-small-elasticsearch` timed out (HTTP 408, deployment not starting) twice on this project.
- Review ids are composed `parent_asin:asin:user_id:timestamp` (dataset has none); 17 of 14,541 collided across the four snapshots (source duplicates), so ids are not guaranteed unique.
- Amazon data has no stock or size availability. Those cannot be hard constraints in generated tasks (unverifiable); do not synthesise them.
- PayPal: capture must send a JSON body (`{}`) or PayPal returns `UNSUPPORTED_MEDIA_TYPE` (live-verified bug, fixed). Agent Toolkit not adopted (required actions unconfirmed).
- Modal: GPU functions require a payment method on the workspace; blocked, $0 spent. The Qwen tool-call numbers are therefore **not measured**; the license (Apache-2.0) and pinned revision `a09a3545...` stand from the earlier spike.
- The Qwen probe moved from `eval/` to `modal_app/qwen_toolcalls.py` (eval/ belongs to agent 2).
- Not verified: that `.env`'s Modal token is the rotated replacement (it authenticates).


## 2026-11-01 integration/runtime owner: measured results
Evidence: `docs/handoffs/integration-runtime.md`. Branch `feat/integration-runtime`.
- **Base**: `main` had neither feature branch merged (`7f2c52e`). Work starts from the verified merge commit `6782e35` (platform + core). `main` was not touched.
- **Enumeration**: `SnapshotCatalog.iter_products(category)` pages with `search_after` (no 10,000 window). `ElasticCatalogProvider.search("")` now raises; `catalog.training.TrainingCatalog` routes the empty-query call that `tasks.engine.build_task` makes to the explicit enumeration. Live: 590 products enumerated across 4 categories, id-ordered.
- **Review ids**: all 17 legacy collisions were byte-identical duplicate rows in the source (same text/title/rating/votes). New id `amazon2023:parent_asin:asin:user_id:timestamp[:n]` (n = repeat ordinal in stream order); original key kept in `source_review_key`, plus `source_ordinal` and `source_record_sha256`. Live index migrated in place: 14,541 reviews, 14,541 distinct ids (17 with ordinal suffix); embeddings reused, no embedding calls. Manifest digests recomputed (`legacy_sha256` kept).
- **Complete review-id lookup**: `review_ids()` and `get_reviews(focus=None, limit=N)` page past 10,000 (unit-tested with 25,000 reviews against a fake that enforces the window). Focused (hybrid) retrieval stays capped at the RRF window (<=100).
- **Memory**: `TraceMemoryProvider` implements `agents.memory.MemoryProvider` over any `TraceRepository` (Elastic or in-memory). Persists every episode; retrieval excludes `test` AND `held_out_category` (stricter than `split != test`), killed, below-threshold and the requesting task's own episodes, re-checked in Python after the query. Order: same category, similarity (4 dp), fitness, episode id.
- **Checkpoints**: `memory.checkpoints.CheckpointStore`: temp file + fsync + `os.replace`, sha256 envelope, cross-process lock, idempotent `create`/`complete`, `finalize` only when every pair is recorded.
- **Quote**: `payments.quote.Quote(subtotal, tax, shipping, currency, total, source, as_of, basis)`. Budget is enforced on `quote.total` before `create_order`. The snapshot has no tax/shipping data, so its quotes are `basis="snapshot_declared"` (list price defined as all-in, tax=shipping=0 by policy) and are disclosed in the API; `require_verified=True` rejects them.
- **Cross-boundary fix (agent 2's `scoring/gate.py`)**: the gate required `variants[variant] > 0`, but the snapshot has no inventory, so EVERY real purchase scored G=0 (observed live: fitness -0.03). Changed to enforce stock only when the source provides `variants`. Known zero stock still fails. One line, isolated commit; revert if agent 2 objects.
- **Real tasks**: `scripts/generate_tasks.py` -> `data/tasks/tasks_v1.json` (48 tasks, 12 impossible by stratified mix, no size/stock/review-trap claims). `tasks.engine.LeakageGuard` rejects 5 of 48 (test-split tasks share feasible products with train tasks): with 4 broad dataset categories and ~150 products each, category-level tasks overlap by construction. Product-type sub-categories (from `attributes.categories`) are needed for tasks that can be product-disjoint. Not changed here.
- **Search realism**: tasks use the dataset category (e.g. `Sports_and_Outdoors`) which no shopper would type. The scripted shopper searches with title words of its target; a real model has no such hint. 4 of 40 (genome, task) pairs could not be scripted ("search surfaced too few candidates").
- **Scripted shopper is not a model.** It reads the task's reference answer. Its scores (genome means 0.967-0.980) are pipeline evidence only.
- Blocked, not run: Kernel-approved sandbox capture (no `PAYPAL_SANDBOX_BUYER_*`), Qwen probe (Modal: "Please add a payment method to use L4 GPU functions").
