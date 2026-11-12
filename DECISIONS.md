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

## 2026-10-31 integration owner (agent 1): operational world
- **Merge**: `feat/platform-m1-m3` fast-forwarded, `feat/core-m2-m5` merged `--no-ff`; baseline 140 passed held. `feat/core-generation` and `feat/integration-runtime` (earlier parallel attempts) were **not** merged; read only for design reference. The packaging commit landed on `main` just before `feat/operational-world` was branched.
- **Frozen contracts**: `FrozenCatalogProvider.iter_products(category, manifest_hash)` replaces `search("")` enumeration; the manifest hash is the snapshot identity (sha256 of sorted product + canonical review ids) and a wrong hash raises `SnapshotMismatch`. Review ids for grounding come from `get_review_ids` (paged with `search_after`, proven complete against the exact hit count, typed result for a missing product).
- **Canonical review id** = `amazon2023:<parent_asin:asin:user:ts>[:n]` (n numbers byte-identical source repeats). I first wrote a hash-based id, then found the live index already used this scheme (migrated by an earlier session) and adopted it rather than re-migrating. 17 collisions are gone (14,541 review docs; manifests rehashed from the live index).
- **Gate**: `OUT_OF_STOCK` only when a task requires a variant. Amazon data has no stock/size; without this every purchase would score G=0.
- **Quote**: budget and PayPal amount use `quote.total`; unknown shipping/tax are `None`; frozen training uses an `item_price_only` quote that never claims to be all-in. The amount is bound into the backend idempotency key so a re-priced order cannot replay an old order.
- **Traces**: stored for every episode (dashboards), but retrieval (query filter + client-side re-check) excludes `test`, `held_out_category`, killed, unscored and sub-threshold traces; malformed documents are dropped.
- **Checkpoint**: content-hashed JSON, temp+`os.replace`; Modal Volume = same store with `commit`/`reload` hooks. Lease expires after 30 min so a preempted runner cannot wedge a generation.
- **Scripted agents** are privileged (they read the reference answer). Fixture genomes deliberately trigger K001/K002/K003/K008; K004/K006/K007 are pre-empted by the action state machine (`InvalidActionOrder`) and cannot be reached by a legal episode.
- **Modal**: CPU-only (`cpu=1, memory=1GiB`), `max_containers=1`, schedule attached only when `CRUCIBLE_ENABLE_SCHEDULE=1` at `modal deploy`. The Elastic key is sent to Modal as a per-run secret from the launcher's environment.
- **Phase 8 blocked**: `PAYPAL_SANDBOX_BUYER_EMAIL/PASSWORD` absent from `.env`; `scripts.paypal_live_check` is ready and stops with exit 3, printing names only.
- **`/agent/run`** answers 503 `model_unavailable` until a model runner is injected; no placeholder agent answers shoppers.

## 2026-11-03 release-final (agent A)
- **Milestone tags**: `m1-day1-checks` on `7d4e93e` (merge of the Day-1 catalog/PayPal-Kernel/Modal spikes); `m2-catalog-tasks` on `6782e35` (earliest commit containing the snapshot builder, provider router and task engine; it also already contains the first episode runner and the Kernel/sandbox spikes, so it is the earliest merge that satisfies m2 and m3); `m3-episode` on the release-final merge commit as instructed, although `61ffbab` ("run bounded scored episodes") is where single-agent episodes first landed.
- **Duplicate-capture assertion**: live PayPal answered a second capture under a new `PayPal-Request-Id` with 2xx while the order held exactly one capture. The live check now proves "no double charge" by the order's own capture list, and records the response code as observed (not as `ORDER_ALREADY_CAPTURED`).
- **Kernel approval is not reliable** (1 end-to-end pass in 8 authorized runs, plus 1 earlier). README and spike doc say so; judges approve by hand in PayPal's page. The Kernel browser geo-locates to a non-English login page, so `Accept-Language: en-US` is sent (a plain header; no stealth/proxy). The challenge-text regex is English only.
- **Ledger** behind `PAYMENTS_BACKEND=sandbox` is in-process (lost on restart); `/payments/ledger` serves it read-only and sanitized (no URLs, credentials or payer data).
- **Model gate**: the API attaches Qwen only when `CRUCIBLE_MODEL_BACKEND=qwen` AND the human-set Modal launch gates exist; otherwise typed 503 `model_unavailable`.
- **Return URL** (2026-11-03): `PAYPAL_RETURN_URL` / `PAYPAL_CANCEL_URL` env configure the sandbox order's redirect targets (default stays the example.com placeholders). The Kernel approver treats a redirect to that return host as success; the PayPal API status remains the proof.
- **Brand masking** (2026-11-03): enforced once, in the API (`api/masking.py`), for `/catalog/*` and buyer `product_card`/`comparison`/`review_citation`/confirmation text. Text only; undetected free-text brand mentions are a known gap. The web shows "Brand not shown" when the API sends `brand: null`.
- **Agent B merge** (2026-11-03): `READY-TO-MERGE ded4e44` merged into main after `uv run pytest -q` = 542 passed, 1 skipped.
- **Tags m6-product, m7-polish** (2026-11-03): created on request at the submission-package commits although their prompt.md contents are not all met (no Render deploy, no Astropods, no final evaluation). `m4-world` and `m5-train-eval` were not created because their contents (Modal-trained, evaluated model) do not exist. `docs/submission/PRE_SUBMIT_CHECKLIST.md` states the real status of each.
- **Postman duplicate capture** (2026-11-03): the collection now accepts either a 422 `ORDER_ALREADY_CAPTURED` or a 2xx that leaves one capture (live sandbox behaviour); step 10 proves one capture.
- **Graph refresh** (2026-11-03): `graphify update .` is AST-only, so `docs/graph/` reflects code, not re-extracted docs.

## 2026-11-05 GRPO (agent B, `feat/grpo-rl`)
- **Custom GRPO loss on the existing PEFT backend, not TRL `GRPOTrainer`.** Criteria: (1) *fit*: `GRPOTrainer` samples its own
  completions from a prompt dataset (its multi-turn path runs tools through its own `environment_factory` loop); our rollouts are
  multi-turn tool-call episodes produced and scored by the world (fitness, kill rules), so TRL would either re-generate them
  (off our world, off our scorer) or need its rollout path replaced. (2) *pins*: current TRL needs newer `transformers`/`peft` than
  the pinned `transformers 4.49.0` / `peft 0.14.0` / `torch 2.6.0`; an older TRL would freeze us on an early GRPO implementation.
  (3) *code*: the clipped-ratio + k3-KL objective is ~40 lines on top of `torch_backend` and reuses the trainer, resume, artifact
  and gates unchanged; TRL would add a dependency plus an adapter layer around its Trainer state that breaks our bit-identical resume.
  No new dependency. Reference policy = base via PEFT `disable_adapter()` on the same weights (no second model copy).

## 2026-11-08 scaling plan (proposed, not implemented)
Status: recommendations agreed in discussion; nothing built yet. Order of work = order below.
- **Checkpoints: append-only, not rewrite-per-episode.** Today `GenerationStore.record_episode` reloads the Volume, rewrites the
  whole state (all outcomes so far), fsyncs and `volume.commit()`s per episode: O(N²) bytes, N commits. Plan: write base state
  once; one small `gen.<id>.ep.<key>` file per episode via `create_exclusive` (dedup for free); `finalize` compacts and deletes the
  small files; `commit` every K episodes / T seconds (a crash loses <= K idempotent, re-runnable episodes). Retention: drop Volume
  state for completed generations after N (already published to Elastic via `generation_doc`); keep LoRA adapters for survivors only.
  Checkpoints stay: they are what saves paid GPU reruns.
- **Trace endpoints aggregate in Elastic.** `api/world.py` pulls up to `MAX_SCAN` traces into memory via `all_traces()` and counts
  in Python. Plan: `terms` aggregations for kill/payment counts; exports/replays stream (generator + NDJSON `StreamingResponse`).
- **Latency, by lever size:** (1) fewer model steps: richer tool results (search returns top-k + review summary), since each step
  is a full inference round-trip; (2) `POST /agent/runs` returns immediately and the agent emits events per step (polling `?after=seq`
  already exists) instead of blocking until `agent.run` ends; (3) parallel fan-out of independent tool calls in one step, prefetch top
  search results while the model generates; (4) short-TTL cache for the live catalog. Already in place: PayPal token cache, reused
  `httpx.Client`, vLLM batching + response cache, `FrozenCache`.
- **Shared state = one Redis (Render Key Value), only when a 2nd API instance is added.** In-process today: `BuyerService._runs`/
  `_confirming`, `GuardedPayments._pending`, `RateLimit`. Mapping: run = hash + event list (`LRANGE` for `?after=seq`), confirm lock
  = `SET NX EX`, pending orders = hash with TTL, rate limit = `INCR`+`EXPIRE`. PayPal `PayPal-Request-Id` remains the double-capture
  backstop. Not done now: `render.yaml` runs one free instance (YAGNI).
- **Queue: only for agent runs.** POST enqueues, any worker runs and appends events to Redis (Redis Streams/RQ: same dependency as
  shared state). Not for generation episodes (Modal map/spawn already is the queue), not for catalog/payment calls inside a run
  (request/response; a hop adds latency), and messages carry blob keys, never large payloads.

## 2026-11-08 inference cost, observatory, security (`feat/batched-inference-observatory`)
- **Serving**: vLLM with prefix caching and multi-LoRA, behind `@modal.batched`. A batch is grouped by adapter: one `llm.generate` per group with a single `LoRARequest` (or `None` for base), never a mixed list. Each result's GPU cost = `generation_seconds / batch_size`; latency stays the true wall time.
- **Response cache**: on-disk, keyed on the full request. A hit costs $0. An entry that is corrupt, or that came from a different model/revision/adapter, is ignored, never replayed.
- **1.5B option** added next to 7B for cheaper runs; 7B stays the default target. Concurrent episodes must record the same outcomes as serial (tested).
- **Observatory** (`/observatory`): shows only what the replay holds. No base-model/algorithm claims, no "7B" badge. The agent is named by its real id plus checkpoint; stages that have not run say "Not run yet"; the kill list comes from the API's rules; the population count is "culled" (population − survivors). Honors `prefers-reduced-motion`. New deps are pinned exactly.
- **Order ids** (supersedes the 2026-10-30 idempotency line for API callers): the API prefixes the task with `api:<request_id or random uuid>`, so pending ids are unguessable and two callers with the same body (e.g. the README "judge" example) no longer share an order. Clients that want safe retries send `request_id` (16–64 chars of `[A-Za-z0-9_-]`).
- **Rate limit**: in-process 60 s sliding window on POST `/agent/run` and `/purchase/*`. 10/min per client (`CRUCIBLE_RATE_LIMIT_PER_MINUTE`) and 60/min in total (`CRUCIBLE_RATE_LIMIT_TOTAL_PER_MINUTE`), returning 429 `rate_limited`. Clients are identified by the left-most `X-Forwarded-For` entry, which is spoofable; the total cap is the real backstop. Render's proxy header behaviour has not been verified.
- **Bounds**: pending orders are capped at 1,000 (oldest evicted). Buyer run ids need at least 16 chars. `x-request-id` is echoed only if it matches `^[A-Za-z0-9_-]{1,64}$`. Request id fields have length limits.
- **Web**: a PayPal approval link renders only when it is https on `paypal.com` or one of its subdomains. Headers: `frame-ancestors 'none'` + `X-Frame-Options DENY` (clickjacking on confirm), nosniff, strict referrer, Permissions-Policy. A full script CSP is deferred because three.js and AG Grid need extra setup.
- **GPU pins bumped** off ~90 published advisories: vllm 0.32.0, torch 2.13.0, transformers 5.19.0, peft 0.21.2 (full list in `GPU_READINESS.md`). The real-library CPU tests pass 6/6 on both the old and the new pins. Not verified: CUDA 13 on Modal L4, and the Qwen probe on the new image (it passed only on the old one). `modal_app/day1_probe.py` and `docs/model-runs/grpo-offline-e2e/STATUS.md` keep the old pins as historical records.
- **Open, not fixed**: 18 unreachable git blobs (some hold old `.env.example` keys) need key rotation, then a user-approved `git gc --prune=now`. The sandbox ledger lives in memory. The API has no auth (judges by design). The reviews route does not brand-mask in demo mode.
- **Local run**: the API runs with `DEMO_MODE=1 uv run --env-file .env uvicorn api.main:app --reload` (the API never loads `.env` itself). The web runs with `NEXT_PUBLIC_DATA_MODE=live` against `http://localhost:8000`.
- **Live model results** (`GET /models/live`, the panel on `/models`): numbers show up as they land on disk, not only once a run is published to Elastic. The endpoint reads:
  - every `docs/**/*probe*.json` with `experiment: qwen-bounded-probe`, returning only the rates (with numerator and denominator), cost, p50/p95 latency and status; never records or model text.
  - every `CRUCIBLE_EVAL_ROOT/*/manifest.json` (default `checkpoints/evaluations`), returning per-contender episodes done vs expected, kills and cost. No success rate is computed there, so no unscored number appears; scores still come only from the published report.
  - The page calls `router.refresh()` every 30 s while the tab is visible. On Render the eval store is not on disk, so there only probes committed to the repo and published evaluations appear.
- **Local CORS**: the API must be started with `CORS_ALLOW_ORIGINS=http://localhost:3000`, or the browser's connection indicator shows "API disconnected".

## 2026-11-09 base evaluation attempt, tool contract, 3B (`feat/batched-inference-observatory`)
- **Inference app deployed** (`crucible-qwen-inference`, 7B, L4, max 1 container, scales to zero after 60 s). vLLM 0.32.0 crashed at warmup (FlashInfer sampler JIT needs nvcc/ninja, absent from the image); fixed with `VLLM_USE_FLASHINFER_SAMPLER=0` in the image env. Engine start is ~145 s once scheduled; L4 scheduling alone has taken 15+ min. This resolves the "unverified on the new pins" item: the 7B engine starts and answers on vllm 0.32.0.
- **`search_catalog` was undocumented**: the model guessed filter keys the catalog ignores (`{"price":{"lte":N}}`) and put the category name in `query`; 3/3 pilot episodes returned 0 products and were killed (K001/K002/K004). Now documented (`category`, `max_price`), and a blank `query` browses the filtered category in stable `product_id` order. `PROMPT_VERSION` is `shopper-prompts-v3`; pilots under v1/v2 are archived in `checkpoints/evaluations/_pilot-*` and are not results. Nothing is trained yet, so the training format stays consistent with this contract.
- **`FrozenCache` search key** is canonical JSON of the filters (nested model-supplied filter dicts crashed it with `unhashable type: dict`).
- **Qwen2.5-3B-Instruct added** as `CRUCIBLE_QWEN_MODEL=3b`, pinned `aa8e725…`. License is the Qwen Research License (non-commercial), unlike 7B/1.5B (Apache-2.0). `tests/test_train_cli.py::test_authorized_launch…` is 7B-only and also fails under `1.5b`/`3b` (pre-existing).
- **Run note**: `scripts.run_evaluation` loads only the Elastic and three gate vars from `--env-file`; the Modal token must come from `uv run --env-file .env`. Run a warm-up call with a very long timeout first: the eval client's 120 s timeout is shorter than a cold start.
- **Spend**: Modal billing for 2026-11-09 is $0.677 (`modal billing report --for today`), almost all cold/failed starts; the client's estimate ($0.09) counts generation only and understates real cost. Approved ceiling $0.861948 is NOT raised. The base evaluation (141 episodes, est. ~$0.45 generation) is NOT complete: 0 episodes recorded under v3. Needs a user decision on spend.
- **Episode token budget 10,000 -> 120,000** (`RunnerConfig.max_tokens`). The counter sums prompt tokens over steps and every model call carries ~1.6k tokens of tool schema, so a real model was cut off with "token or cost budget exceeded" after ~4 steps (24 of the first 30 base episodes), long before it could compare or buy. The 20-tool-call cap and the $1.00 cost cap still bound runaway episodes. Results from the 10k run are discarded (not scored, not published). Server idle window is now `CRUCIBLE_QWEN_SCALEDOWN_SECONDS` (default 60); deployed at 300 for the eval run. User approved raising the spend ceiling to $2.00 total on 2026-11-09 (Modal billed $0.677 before that).
- **Base eval status (2026-11-10, STOPPED, incomplete)**: 20 of 141 episodes recorded under `shopper-prompts-v3` + 120k token cap (6 `instant_kill`, 5 `tool_limit`, 9 `MalformedModelOutput`; none completed a purchase). Not a result: no report, nothing published. The Modal GPU container is repeatedly SIGTERM'd 2–15 min after becoming ready even under constant traffic (seen at 01:05 and 01:44 UTC), and each cold start is ~2.5 min of engine init plus L4 scheduling wait, so progress per paid cycle is small. Inference-app billing at stop: ~$1.29 of the $2.00 cap approved on 2026-11-09 (Nov 9 $0.710 + Nov 10 $0.577). Resume with `scripts.run_evaluation run` (episodes are kept). Open: why 9/20 are malformed (raw outputs are not stored, only hashes); seeds are byte-identical so the 3 seeds add no variance (sampling is effectively greedy).
- **Server idle window**: deployed with `CRUCIBLE_QWEN_SCALEDOWN_SECONDS=300`; redeploy without it to return to 60 s.

## 2026-11-09 Observatory: generation picker, 30-shopper crowd, live stream (`feat/batched-inference-observatory`)
- **One bundle per generation** (`GET /observatory/{id}?agents=30`, max 60): focus episode, crowd, leaderboard, kill rules (counted for that generation only) and up to 200 episode rows, in one request instead of 30+. The crowd is picked round-robin across agents, longest episodes first, so it shows the whole population. Crowd steps carry the tool, references and error code only (no tool arguments).
- **Caching**: a published `completed` generation never changes, so its bundle stays in an in-process LRU (16 entries) until restart and is sent with `Cache-Control: public, max-age=3600`. Anything else is cached 5 s. Measured locally: 235 ms cold, 9 ms cached.
- **Picker**: `GET /observatory/generations` merges published generations with generation ids found only in the traces index (Elastic `terms` aggregation), shown as `unpublished`: running or interrupted, no summary yet. The page takes `?generation=<id>`.
- **Live**: server-sent events (`GET /observatory/{id}/live`), not WebSockets: one-way, plain HTTP, auto-reconnect in the browser. The API polls every 3 s, checking the trace count first, and rescans only when the count changed. Each stream closes after 15 min and the browser reconnects. Events: `status`, `episode`, `training`. New episodes join the crowd and the oldest leave at 30.
- **Training progress** goes through a Modal Dict (`crucible-live-training`), written from inside the training container with no extra secret, at most once every 2 s plus every status change. A failed write is ignored and never fails a paid step. It holds numbers and ids only. The API reads it only with `CRUCIBLE_LIVE_TRAINING=modal`. Rejected: Elastic (the GPU container has no Elastic secret), and the Volume (it would need a reload per read).
- **API on Modal** (`modal_app/api_server.py`): optional, CPU 0.5 core, `min_containers=0`, so idle costs $0 and nothing runs on the laptop but the browser. Written but not deployed; deploying is the user's call.
- **3B**: `CRUCIBLE_QWEN_MODEL=3b` (already pinned) is the documented choice for the live-training demo. Its Qwen Research License is non-commercial, unlike 7B/1.5B.
- **Not done**: no training run was started, so the training card has only been seen in tests. Sample mode has no crowd or picker (fixtures hold one episode).
- **2026-11-10 container replacement, diagnosed (probably)**: with `min_containers=0` the GPU container was SIGTERM'd 2–15 min after becoming ready, mid-run, with nothing logged before it. With `CRUCIBLE_QWEN_MIN_CONTAINERS=1` it ran 17 min under 12 concurrent workers (83 episodes) with no replacement; the only SIGTERM was our own stop. So the earlier kills were Modal's idle scale-down, not preemption or our `cancel()` (Modal docs: plain `FunctionCall.cancel` does not terminate containers). Fix = keep one container warm for the duration of a run (bills ~$1.1/h) and stop the app afterwards; the server now logs `[batch] n= seconds=` per batch. Not proven why Modal judged a busy container idle.
- **Model observations are blind (blocker for any real-model eval or training)**: `render_messages` shows a tool result as only `{references, summary, error_code}`, and the executor's summaries are one-liners ("product detail found", "returned 10 reviews", "compared 10 products"). The model never sees titles, prices, ratings, variants or review text, so it cannot check the budget, compare, or cite evidence; 50/83 base episodes ended `MalformedModelOutput` (44 right after `get_reviews`, where `summarize_review_evidence` needs real review ids and claims) and 27 hit the tool cap. The 83 v3 episodes are archived in `checkpoints/evaluations/_pilot-v3-blind-observations/` and are NOT results. The SFT/RL renderer is the same function, so a trained model would inherit the blindness. Proposed fix (needs approval, changes the record/trace contract and `PROMPT_VERSION` -> v4): put a compact content payload (id, title, price, rating, variants; review rating/title/text truncated) in what the model sees.
- **Spend**: Modal inference app billed ~$1.87 of the $2.00 approved (guard stopped the run at $1.868; billing lags real use). App `crucible-qwen-inference` is STOPPED (not deployed); redeploy needed. No further GPU spend without a new decision.
- **2026-11-10 model observations now carry content (PROMPT_VERSION `shopper-prompts-v4`)**: `RecordedToolCall.result_content` (optional; old records load unchanged) is filled by the executor and shown to the model/trainer as `tool_result.content` by `render_messages`, SFT curation and RL rollouts. search: id/title/price/brand per product; get_product: + category, in-stock variants, top 3 features (120 chars); compare: id/title/price/variants; get_reviews: id, rating, verified, helpful_votes, text (300 chars). Titles cut at 100 chars. Measured on the live catalog: ~4k tokens of added content per full episode (history is resent each step, still well inside the 120k cap). Tools now have descriptions, including the `variant` convention (`default` when a product lists none). Scripted agents' behavior is unchanged (they read the catalog directly); only the model-visible text changed. User approved raising the Modal ceiling by $1.00 (to $3.00 total) on 2026-11-10 for a clean v4 base run.

## 2026-11-09 Learning rounds in the Observatory
- The agents learn in rounds, not continuously. `scripts.run_loop` runs world rollouts, then curate, audit, plan, train, evaluate and re-entry; the new adapter acts in the next round. "Watching them learn" therefore means watching each round's world run live, then the training card, then the next round, plus a fitness-per-round chart. `GET /observatory/rounds` reads the loop's stage files (`CRUCIBLE_LOOP_ROOT`). Metrics come from `summary.json` once a round's world run is finished, or from its traces while it runs, recomputed only when the trace count changes. Rounds are also pushed on the live stream (`rounds` event).
- The Modal-hosted API does not see local loop files. Rounds show there only if the loop runs where the API runs. Live episodes and training progress do not depend on this.
- `run_loop --concurrency N` is passed to the generate stage, so 30 agents share vLLM batches instead of queuing one by one. The cost split per batch was already in place. It is not an iteration setting, because outcomes are identical to serial.
- Verified at $0: two dry-run rounds (`dry-1`, `dry-2`, scripted, offline) appear in the panel; a scripted world run `live-demo-20261109` (30 genomes × 4 tasks, traces to Elastic) streamed into the Observatory live (7, then 19, then 36 new episodes at 4/10/20 s, crowd full at 30).
- `run_loop --plan` bounds are worst cases (maximum calls per episode, serial, no batching): 3B, 30×4 round about $103–178 in total, mostly evaluation. Spend is actually limited by `CRUCIBLE_MODAL_APPROVED_CEILING_USD` (the client stops there; rerunning resumes) and by the training ceiling.
- **2026-11-10 container replacement, better explanation**: with `min_containers=1` the container was SIGTERM'd at 03:37:23 UTC exactly when the eval client process was killed with requests in flight (it was serving batches normally until 03:37:23). So cancelling in-flight inputs (client killed, or `call.cancel()` after the client's 120 s timeout) takes the whole container down, and every other in-flight request is lost. That fits all the earlier kills (each followed a client timeout or kill), and the one 17-min run with no timeouts or kills was never replaced. Rules: never kill an eval client mid-run (stop the server, or let `--max-episodes` end it); keep the client timeout above the worst queue wait; warm up with a long timeout before starting workers. `FunctionCall.cancel()` on a running input is not safe on this app.
- **2026-11-10 v5 base-eval attempt, STOPPED (16/141, not a result)**: with content-bearing observations and documented tools (prompts v5) the first 16 episodes were 6 `instant_kill` (infeasible budgets) and 10 `malformed_action` (the model calls `get_reviews`/`propose_purchase` before opening or comparing, which the state machine rejects and ends the episode); 0 successes. Not enough data to call it: the harness is now fair, but the run never got past 16 episodes. Archived under `checkpoints/evaluations/_pilot-v*`; the live store has 16 v5 episodes and is resumable.
- **Modal container still not stable**: killed again at 03:58:44 UTC (no deploy, no client kill at that moment; the deploy had finished 8 min earlier) and, after the 03:37:23 kill, Modal did NOT respawn the `min_containers=1` container until a redeploy (16 min of nothing). The "cancel kills the container" theory fits 03:37 but not 03:58, so the cause is unproven and the problem is NOT fixed. What works: a run with no kills and no client timeouts survived 17 min (83 episodes). Untried: replace `@modal.batched` with `@modal.concurrent` + an async engine, or serve vLLM behind `modal.web_server`; both need new GPU spend to test.
- **Spend at stop**: $2.374 billed on the inference app of the $3.00 approved ceiling (`.env` is 3.00). App is stopped; nothing is running. `modal billing report` lags real use; its Description column is truncated (`crucible-qwen…`).

- **2026-11-10 container stable after removing `call.cancel()`**: `modal_transport` no longer cancels a timed-out call (cancelling a running input restarts the container and drops all other in-flight work), the eval client waits 600 s, and the server input timeout is 900 s. With `min_containers=1` the container ran ~20 min under 16 workers and served 41 new episodes with no replacement, and was only stopped by us. The earlier 03:58 kill is still unexplained but did not recur. Cold start this time took ~10 min before the first call returned (L4 scheduling), so warm up with a long timeout.
- **2026-11-10 `input_too_long` is a result, not a backend failure**: three episodes ended `model_failure` after ~54k summed prompt tokens, i.e. the agent's own context passed the 8192-token server limit, and tripped the "3 consecutive backend failures" stop. The failure string now carries the error code (`model failure: InferenceError[input_too_long]`) and `is_backend_failure` excludes it, so these episodes count as base-model failures instead of halting the run. The 3 already-quarantined episodes (batch-20261110-0026 seeds 1-3) carry no code in the store, so they will rerun and, being deterministic, land as `input_too_long` again.
- **2026-11-10 base eval status**: 57/141 records (33 `malformed_action`, 18 `model_failure`, 6 `instant_kill`, 0 successes). Modal billed $2.703 of the $3.00 ceiling; app stopped, 0 containers. Finishing the other 84 records needs roughly $0.5-0.7 more, which is above the ceiling, so it waits on the user raising `CRUCIBLE_MODAL_APPROVED_CEILING_USD`.

## 2026-11-10 Round 1 restart: cold start, GPU queue, stale 7B deploy

- The 3B server's cold start (vLLM engine init ~145 s, plus GPU queueing) outlasted the 120 s agent call timeout, so the first episodes failed as `model_failure` and the circuit breaker paused the round. `run_loop` now sends one warm-up call (900 s timeout) before any episode; if it fails, the round pauses before spending episodes.
- L4 capacity was short: one warm-up waited ~11 minutes in `Pending` (not billed). We kept L4 rather than adding an A10G fallback, which would change the cost basis.
- The live deploy was an older 7B version, so every 3B request came back `model_revision_mismatch`. The warm-up treated that reply as success. It now pauses on any `error_code` reply. Fix used: `modal app stop -y crucible-qwen-inference`, then redeploy with `CRUCIBLE_QWEN_MODEL=3b`.
- Failed attempts were moved out of `checkpoints/loop/it-1` (to scratch) so infrastructure failures never count as model results; the rerun reuses the same episode ids and overwrites their traces.
- Root cause of the 7B server: the deployed container ran a cached 7B image (`CRUCIBLE_QWEN_MODEL=7b` inside it, confirmed with `modal container exec`) even though the local deploy resolved 3b. Redeploying with `MODAL_FORCE_BUILD=1` built a fresh 3B image. When switching models, force the rebuild and check the model with a warm-up call before a round.

## 2026-11-11 First real 7B QLoRA run on an L4 (smoke, scripted dry-run data, pipeline evidence only)
- **Verified on Modal L4**: CUDA 13.0 + torch 2.13.0 + bitsandbytes 0.50.2 NF4 load the 7B in 13-28 s. User approved a $0.50 training ceiling for the smoke (manifest hash `2d630a4a...` = the dry-1 scripted SFT set, 13 records, 2 steps; pause after step 1, then resume).
- **Run 1 failed `example_too_long` (4123 > 2048)**: the cap predated content-bearing observations (v4+); real episodes are 4-5k tokens. `max_sequence_length` default is now 8192 = serving `MAX_INPUT_TOKENS`, so we train on everything the server can see. Changes every plan hash (default moved).
- **Logits only at labeled positions** (`logits_to_keep`, scattered back to `[B, L-1]`): full-vocab logits at 8k are ~12 GB (bf16 + fp32 + grad). SFT now goes through the same `_token_logprobs` as GRPO (`-logp.sum()/targets` equals the old summed CE).
- **Run 2 OOM in backward (2.67 GiB alloc, 17 GiB allocated)**: that size is fp32 `[28 heads, L, L]` attention scores at ~5k tokens, so attention was eager-like. Fixed: `attn_implementation="sdpa"` set explicitly; dropped `prepare_model_for_kbit_training` (it upcast `embed_tokens`/`lm_head` to fp32, +4.4 GB, no benefit under bf16 autocast); non-reentrant gradient checkpointing (PyTorch warned the default is going away); `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` (3 GiB was reserved but unusable). `dtype=` replaces deprecated `torch_dtype=`.
- The training function now logs `[train] load_seconds= loaded_gb=` and `peak_gb= total_seconds=` (read with `modal app logs crucible-qwen-training`).
- **Tests**: tiny-model test cap raised 4096 -> 8192 (real scripted episodes are 4.8k tokens). `test_trained_adapter_loads_in_the_real_inference_engine_and_base_stays_base` fails before and after these changes (random tiny model: adapted greedy output equals base); not a GPU-path test, not fixed.

## 2026-11-12 inference validation hand-off (fork)
- Suite 649 passed, 3 skipped. 3B inference app (`CRUCIBLE_QWEN_MODEL=3b`) served 58 requests with `error=none` under the 3b-pinned client; one early `model_revision_mismatch` (0.00 s, first request, not repeated). Engine ready in 194 s, no container replacement.
- Pilot `pilot-v6-state-tools` (leftover from the previous session) was running; we waited for its `--max-episodes 12` cap instead of stopping the app mid-run (stopping kills in-flight inputs). It ended `interrupted` at 12/141, no error. Inference app then stopped (`modal app stop ... --yes`).
- No separate one-token warm-up was run: the eval's own traffic already proved identity. No ceiling or gate was changed.

## 2026-11-12 gap review and `outline.md`
- Full-codebase gap review done (deadline today 12:00 PM PT). Findings and the ordered fix plan are in `outline.md`: P0 = land the 70 uncommitted files + untracked sources, sync docs, deploy to Render, judge path without a model, placeholders + video + `m8-submission`; P1 = model result only if the Modal ceiling is raised (harness fixes first); P2 = hardening.
- Verified state: pytest 649 passed / 3 skipped / 6 deselected; web tsc, lint, 29 vitest clean; base eval has 86 records on disk (docs said 57) with 0 successes; all 3 SFT smoke runs failed; `check_submission` 14/18.

## 2026-11-12 P0 ship pass: docs synced to the code, 503 explained, scratch notes ignored
- **Base eval is 86/141 on disk, not 57** (53 `malformed_action`, 27 `model_failure`, 6 `instant_kill`, 0 successes) plus 12 quarantined; `STATUS.md` now says "partial, not a result" instead of "planned, not run". *(user asked for the sync)*
- **SFT smoke on L4, all 3 runs failed, no adapter**: `smoke-20261111` `ExecutionError` (`example_too_long`, cap 2048), `smoke2` `ExecutionError` (OOM in backward, cap 8192), `smoke3` `RemoteError` (cause not yet read: pull `modal app logs crucible-qwen-training` before another run). Records: `docs/model-runs/smoke*-20261111/training_run.json`.
- **Modal state (2026-11-12 02:15)**: only `crucible-qwen-training` is deployed (the truncated `crucible-qw...` in `modal app list`). **`crucible-qwen-inference` is NOT deployed** (stopped; verified with `modal.Cls.from_name(...).hydrate()` = `NotFoundError`). This corrects the earlier note that an inference app is still deployed.
- **Why `/agent/run` returned 503**: the shopping chat has no model behind it. Two paths give the same 503: (1) `CRUCIBLE_MODEL_BACKEND` or the human-set `CRUCIBLE_MODAL_*` gates missing, so `BuyerService(agent=None)` raises `ModelNotConfigured` -> `model_unavailable`; (2) gates present (the local API on :8000 reports `model_configured: true`) but the Modal inference app is stopped, so `modal_transport` fails to look it up and `QwenClient._call` maps that to `transport_error`, which `api/main.py` also answers with 503. Not a code bug; no run was started (a live call would have spent money).
- **Chat page says it plainly (user)**: `web/src/components/agent/agent-workspace.tsx` shows "Shopping model is not running" for `model_unavailable` and `transport_error`, with the purchase API steps (README Path A) and the Payments page. Nothing is simulated.
- **"Review grounding: Not measured" bug fixed**: `world-dashboard.tsx` hard-coded the card; it now reads `summary.rates.review_grounding` (numerator/denominator).
- **Scratch notes ignored, not deleted (user)**: `/outline.md`, `/readmeoutlined.md`, `/session*.md` added to `.gitignore`. Already-tracked docs (`README.md`, `DECISIONS.md`, `docs/**`, `prompt.md`) stay tracked: ignoring a tracked file does nothing, and the docs are the deliverable. Nothing committed in this pass *(user)*.

## 2026-11-08 Observatory at scale (session: observability redesign)
Design: `docs/superpowers/specs/2026-11-08-observatory-at-scale-design.md`. Entries marked *(user)* were the user's call; the rest are the agent's, open to override.
- **Project order** *(user)*: 1 Modal runs → dashboard, 3 Observatory at scale, 2 bigger catalog, 4 experiment editor + launch API.
- **Channel3 stays out of the training world** *(user agreed)*: ToS §7 (checked 2026-11-08 at trychannel3.com/terms) bars using Customer Output to train/fine-tune or make synthetic training data, and caching "a significant portion" of it. Sections 4–5 allow live display to end customers. Allowed use: a labelled live-only "Live Internet" layer whose traces never enter the trace store. Also has no review text, so review kill rules can't score it.
- **Catalog expansion source** *(user)*: more Amazon Reviews 2023 categories (33 exist; 4 used). Candidates researched for later: Amazon ESCI Shopping Queries (Apache-2.0; real shopper queries for mission text, no prices), Amazon Berkeley Objects (images/3D, non-commercial), Olist (multi-seller, non-commercial), Wayfair WANDS (licence to confirm). No public Walmart/Flipkart research dataset found.
- **No AWS / no new infra** *(user agreed)*: Render (web + API, free plan; cold start ~50 s, warm before demos), Elastic Cloud (data), Modal (agent runs). Viewer laptop only renders.
- **Modal → dashboard path is Elastic, not the Modal volume**: the API reads Elastic; Modal runs publish there. Gaps fixed: generations sorted newest-first by new `published_at` on the published doc (never the deterministic checkpoint); unfinished/interrupted runs now publish (summary `{}`); new `publish_existing` Modal function (`--action publish`) backfilled `remote-smoke`, `remote-resume`.
- **Scale data is a real scripted run**: `modal-p200-t12-20261108` (200 agents × 12 tasks = 2,400 episodes, ≈$0.10 CPU), in 800-episode chunks (1 h function timeout; checkpoint/resume). No synthetic episodes in the UI.
- **Laptop safety is enforced in code** *(user requirement)*: one compact snapshot per generation (`GET /world/generations/{id}/snapshot`, server caps ≤5,000 episodes / ≤3,000 products, deterministic sample + `sampled` flag); instanced rendering; ≤2,500 moving shoppers, ≤40 labels, DPR ≤1.5, frameloop `demand` when paused. Target MacBook ≥45 fps at 2,400 episodes.
- **World = task**; every world's shop ring shows all catalog categories (visited lit, unvisited dim); products placed per world.
- **Per-world task facts** come from the real `TaskSpec`s (new `tasks.items` in the generation summary); older generations regenerate the task set from seed and keep it only if task ids match the traces, else "budget unknown". The current HUD budget (read from the policy's own `parse_intent`) is replaced.
- **Build in two phases**: A = snapshot/data/motion engine (no visual dependency); B = look and HUD after the user picks a mockup.
- **Long Modal runs use `modal run --detach` in 600-episode chunks**: chunk 1 of `modal-p200-t12-20261108` was cancelled client-side at 278/2400 (checkpointed, resumes without repeats). Measured ≈4.3 s/episode on 1 CPU, so 2,400 episodes ≈ 2.9 h ≈ $0.16; 600 episodes ≈ 43 min fits the 1 h function timeout. Don't run other `modal run` calls against the app while a non-detached run is in flight.
- **Observatory design approved** *(user, 2026-11-08)*; Phase A (data/snapshot/motion engine) starts now, Phase B (look) after mockup pick.
- **Phase A built** (`feat/observatory-scale`): `summary.tasks.items` carries each task's real budget/kind; `GET /world/generations/{id}/snapshot` (built by `api/snapshot.py`, cached per `(id, published_at)` for completed runs, 8 entries); typed client + Zod; pure motion engine (`web/src/components/observatory/motion.ts`, `BUDGET` constants); `/observatory/perf` harness. Snapshot of a 96-episode run = 27 KB, so 2,400 ≈ 0.7 MB.
- **Snapshot sample ships in its own lazily loaded chunk** (`web/src/generated/snapshot-sample.json`): `samples.json` already rides in a shared client chunk, so a big fixture there would slow every page.
- **World spacing scales with category count** (2·ring radius + 4) so 30+ categories after project 2 never overlap worlds.
- **Running-generation snapshots are never cached**; only `completed` ones are.
- **Review fixes (Phase A)**: backfills keep each run's own time (report mtime) so republishing never reorders the archive; a running run's scripted/model label comes from trace checkpoints and is `null` ("source not yet known") when nothing is recorded, never "Qwen" by default; `limits.episodes_expected/episodes_untraced` expose scripted skips that have no trace; review steps stay on the product being read.
- **Deferred to project 2**: `ElasticReader.all_traces` caps at 20,000 traces, which would undercount and skew snapshots past 20k episodes (not reachable at 2,400).
- **Integration to main (2026-11-08)** *(user asked)*: `main` fast-forwarded `2513e1b..ed3af37` (= `feat/observatory-scale`, which already contains all 4 `feat/batched-inference-observatory` commits) and pushed. Every other local branch was already merged. Skipped: `wip/kernel-approver-leftover` (its commit says superseded on main), `wip/web-screenshot-leftover` (one stale screenshot). Not committed: the main checkout's uncommitted work (18 modified + new models live-results files) — it belongs to a still-active session; it sits on `feat/batched-inference-observatory`, so it merges cleanly when that session commits. Modal run not paused (it never touches git). Secret scan with env values: the only hits match `CRUCIBLE_MODAL_APPROVED_CEILING_USD` (a dollar ceiling, already documented), not a credential.

## 2026-11-12 landing: commits, main merge, raw output kept
- **Landed (user)**: 7 logical commits on `feat/batched-inference-observatory` (gitignore, agents/modal, training, api, web, docs, P1 audit), then `origin/main` (Observatory Phase A, 14 commits) merged in; `main` fast-forwarded to `adb2665` and both branches pushed. Conflicts: `DECISIONS.md` (kept both) and `api/world.py` (module-level `gen_out` plus main's `published_at`). Suite after merge: 670 passed, 3 skipped; web tsc and lint clean, 37 vitest passed. Not re-run: `npm run build`, Playwright.
- **Raw model output is kept (user)**: `QwenModelAdapter.audit` and `ModelOutput.raw_output` hold the model's text, so malformed actions can be debugged; test renamed to `..._and_keeps_raw_text_for_debugging`. Consequence: `EpisodeRecord.model_metadata` (stored in traces, Elastic, replays) now carries that text. It is model output only (tool-call JSON, which already repeats the shopper message), but traces get larger.
- Note: the 2026-11-08 Observatory section now sits after the 2026-11-12 sections in this file (merge order, content unchanged).
