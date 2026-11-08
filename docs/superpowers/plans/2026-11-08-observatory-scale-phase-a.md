# Observatory at Scale — Phase A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serve one compact, capped snapshot per generation and animate every episode of it in the browser within a fixed MacBook budget — the data and motion layer the Phase B look is built on.

**Architecture:** Python builds the snapshot from the generation doc + its traces (pure function, cached per `(generation_id, published_at)`), exposed at `GET /world/generations/{id}/snapshot`. The browser validates it with Zod and drives one `InstancedMesh` from a plain `Float32Array` via a pure TS motion engine; React/Zustand hold only clock + focus + selection. Phase A ends with a perf harness route proving the budget on the real 2,400-episode run; it does not restyle `/observatory`.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, pytest (`uv run pytest`); Next.js 16, React 19, R3F 9, drei 10, Zustand 5, Zod 4, Vitest (`npm test` in `web/`).

**Spec:** `docs/superpowers/specs/2026-11-08-observatory-at-scale-design.md`

**Worktree / branch:** `/Users/nityanthmaramreddy/Downloads/crucible-observatory`, `feat/observatory-scale`. The main checkout (`Downloads/Crucible `) has another session's uncommitted work — never edit or commit there.

## Global Constraints

- No new dependencies (Python or npm). No new infra.
- Server caps: ≤ 5,000 episodes, ≤ 3,000 products per snapshot; beyond, deterministic sample + `limits.sampled = true`.
- Browser budget constants (exact): `MAX_SHOPPERS = 2500`, `MAX_PRODUCT_INSTANCES = 3000`, `MAX_LABELS = 40`, `MAX_DPR = 1.5`.
- Path stop kinds (exact): `0 spawn · 1 exchange · 2 shop(ref = category index) · 3 product(ref = product index) · 4 checkout · 5 refusal`; `ref = -1` when unused.
- World = task. Every world's ring = all snapshot `categories`.
- No synthetic episodes anywhere in UI or sample data. Positions are display coordinates, not semantics.
- Every non-obvious choice made while building gets a bullet in `DECISIONS.md` (`## 2026-11-08 Observatory at scale` section).
- Commits end with `Claude-Session: https://claude.ai/code/session_013SvjDarnyrqv2r9vCgjNiq`.

## Review Focus

1. Generation that is still running / has zero traces → snapshot with `episodes: []`, HTTP 200, not 500. (Task 3 test)
2. Episode with no tool calls (`script_unavailable`) → path `[[0, -1]]`, still rendered at spawn. (Task 2 test)
3. Trace category missing from `data/manifests` → appended to `categories`, never a dangling ref. (Task 2 test)
4. Product dropped by the 3,000 cap but referenced in a path → that stop falls back to `[2, categoryIndex]`. (Task 2 test)
5. Snapshot larger than the shopper budget (e.g. 5,000 episodes) → browser renders exactly 2,500, same subset every load. (Task 6 test)

---

### Task 1: Real per-task facts in the generation summary

**Files:**
- Modify: `world/report.py` (`summarize`, the `"tasks"` dict)
- Modify: `world/publish.py` (add `task_items`, `with_task_items`)
- Modify: `modal_app/world_runner.py` (`publish_existing`)
- Test: `tests/test_world_runtime.py`, `tests/test_world_publish.py`

**Interfaces:**
- Produces: `summary["tasks"]["items"]: list[{"id": str, "category": str, "max_total": str, "impossible": bool, "review_trap": bool}]`, ordered as the task tuple.
- Produces: `world.publish.task_items(tasks: Sequence[TaskSpec]) -> list[dict]` (the shape above; `max_total` is `str(Decimal)`).
- Produces: `world.publish.with_task_items(summary: dict | None, tasks: Sequence[TaskSpec], task_ids: Sequence[str]) -> dict | None` — returns summary with `tasks.items` set only when `[t.id for t in tasks] == list(task_ids)`, else summary unchanged; `None` stays `None`; existing `items` never overwritten.

- [ ] **Step 1: Failing tests**
  - In `test_full_generation_survives_kills_fixtures_and_never_buys_badly` add: `items = s["tasks"]["items"]; assert [i["id"] for i in items] == [t.id for t in world[1]]; assert sum(i["impossible"] for i in items) == s["tasks"]["impossible"]; assert all(isinstance(i["max_total"], str) for i in items)`.
  - In `tests/test_world_publish.py`: `test_with_task_items_only_when_ids_match` — using `generate_tasks(SyntheticFrozen(), HASHES, seed=SEED, count=8, review_traps=1)` (import from `tests.test_world_runtime`): matching ids → `items` length 8; shuffled ids → summary returned unchanged; `None` → `None`; summary already holding `items` → unchanged.
- [ ] **Step 2:** `uv run pytest -q tests/test_world_runtime.py tests/test_world_publish.py` → FAIL (`KeyError: 'items'`, `ImportError`).
- [ ] **Step 3:** Implement `task_items` / `with_task_items` in `world/publish.py`; `summarize` sets `"items": task_items(tasks)`. In `publish_existing`, when the summary lacks `tasks.items`: `generate_tasks(FrozenCache(ElasticCatalogProvider(es)), load_manifest_hashes(), seed=cp.seed, count=len(cp.task_ids))` then `with_task_items(summary, regenerated, cp.task_ids)`; wrap regeneration in `try/except Exception` → publish without items (log the class name).
- [ ] **Step 4:** Same pytest command → PASS.
- [ ] **Step 5:** Commit `feat(world): publish real per-task budget and kind with each generation`.

### Task 2: Snapshot builder (pure)

**Files:**
- Create: `api/snapshot.py`
- Test: `tests/test_world_snapshot.py`

**Interfaces:**
- Consumes: `TraceRecord` (`memory`), generation doc dict as returned by `WorldReader.generations()`, `summary.tasks.items` (Task 1).
- Produces: `build_snapshot(gen: dict, traces: Sequence[TraceRecord], categories: Sequence[str], *, max_episodes: int = 5000, max_products: int = 3000) -> dict` with exactly the spec's shape:
  `generation_id, published_at, scripted, policy, population_size, survivors, kills, categories[{id,name,product_count}], worlds[{task_id,category,budget,impossible,review_trap,request}], agents[{id,variant,fitness,survivor,kill_rules}], products[{id,category,mentions}], episodes[{id,agent,world,path,termination,killed,fitness}], limits{episodes_total,episodes_included,products_total,products_included,sampled}`.
- Produces: `path_for(calls: list[dict], product_index: dict[str, int], category_index: int) -> list[list[int]]`.

Rules the tests pin:
- Path: always starts `[0,-1]`. Per tool call (`c["action"]["type"]`): `parse_intent` → spawn; `search_catalog` → `[1,-1]`; `report_no_match` → `[5,-1]`; type containing `purchase` or `pay` → `[4,-1]`; anything else → first `result_references` id in `product_index` as `[3,i]`, else `[2, category_index]`. Consecutive duplicate stops collapse.
- Sampling when `len(traces) > max_episodes`: keep the `max_episodes` traces with the smallest `sha256(episode_id)` hex; output ordered by `episode_id`.
- Products: mentions counted over included traces' `products_considered`; keep top `max_products` by `(-mentions, id)`.
- `categories` = given list, then any trace category not in it (sorted); `name` = underscores → spaces; `product_count` = included products in that category.
- `worlds`: one per distinct `task_id` (sorted); `budget`/`impossible`/`review_trap` from `summary.tasks.items` when present, else `None`; `request` = first trace's `task_text`.
- `agents`: from `summary.population` (`id`,`variant`), else distinct trace `agent_id`s; `fitness` = `summary.fitness.by_genome[id]` as float or `None`; `survivor` = id in `summary.survivors`; `kill_rules` = sorted keys of `summary.kills.by_agent[id]`.
- `scripted` = `summary.params.model == "scripted"` or `summary.policy == "scripted-v1"`.
- Episode `fitness` = `t.fitness if t.scored else None`; `termination` = `t.episode.get("termination", "unknown")`.

- [ ] **Step 1: Failing tests** (`tests/test_world_snapshot.py`, traces from `tests.test_api_world.traces()` and `GEN`):
  - `test_shape_and_indices_are_consistent`: every `episode.agent < len(agents)`, `episode.world < len(worlds)`, every `[3,i]` has `i < len(products)`, every `[2,i]` has `i < len(categories)`.
  - `test_paths_start_at_spawn_and_end_where_the_episode_ended`: `path[0] == [0,-1]`; terminations `success` → last kind `4`; `no_match` → last kind `5`.
  - `test_empty_tool_calls_path_is_spawn_only`: trace with `episode={"tool_calls": []}` → `[[0,-1]]`.
  - `test_unknown_category_is_appended`: `categories=["Office_Products"]`, traces in another category → that category appended, refs valid.
  - `test_product_cap_falls_back_to_shop`: `max_products=0` → no `[3,_]` stops, `limits.products_included == 0`.
  - `test_episode_cap_is_deterministic`: `max_episodes=2` twice → identical ids, `limits.sampled is True`, `episodes_total == 3`.
  - `test_world_facts_from_task_items_else_unknown`: GEN with `summary.tasks.items` → budget string present; GEN without → `budget is None`.
- [ ] **Step 2:** `uv run pytest -q tests/test_world_snapshot.py` → FAIL (module missing).
- [ ] **Step 3:** Implement `api/snapshot.py`.
- [ ] **Step 4:** Same command → PASS.
- [ ] **Step 5:** Commit `feat(api): compact capped world snapshot builder`.

### Task 3: Snapshot endpoint

**Files:**
- Modify: `api/world.py` (inside `world_router`)
- Test: `tests/test_api_world.py`

**Interfaces:**
- Consumes: `build_snapshot` (Task 2), `reader.generations()`, `reader.all_traces(generation_id)`, `catalog.providers.elastic.load_manifest_hashes()` for category order (sorted keys).
- Produces: `GET /world/generations/{generation_id}/snapshot` → 200 JSON (shape of Task 2), 404 `generation_not_found`. Cached in a module dict keyed `(generation_id, published_at)`, max 8 entries (drop oldest), only when `status == "completed"`.

- [ ] **Step 1: Failing tests**: `test_snapshot_endpoint_returns_capped_shape` (client fixture: 200, `generation_id == "g1"`, `len(episodes) == 3`); `test_snapshot_for_unknown_generation_is_404`; `test_snapshot_of_running_generation_with_no_traces_is_empty_not_error` (InMemoryReader with GEN `status="running"`, no traces → 200, `episodes == []`).
- [ ] **Step 2:** `uv run pytest -q tests/test_api_world.py -k snapshot` → FAIL (404 route).
- [ ] **Step 3:** Add the route **before** any `/world/generations/{generation_id}` catch-all ordering issue (FastAPI matches the longer literal path fine; verify).
- [ ] **Step 4:** Same command → PASS; full `uv run pytest -q tests/test_api_world.py` → PASS.
- [ ] **Step 5:** Commit `feat(api): GET /world/generations/{id}/snapshot`.

### Task 4: Real sample snapshot (after the Modal run completes)

**Files:**
- Create: `scripts/export_snapshot.py`
- Create: `docs/api/samples/world_generation_snapshot.json`
- Modify: `web/scripts/generate-samples.mjs` (add filename), `web/src/generated/samples.json` (regenerated)

**Interfaces:**
- Produces: `uv run python -m scripts.export_snapshot --env-file "<path>" --generation-id <id> --out <path>` — calls the app in-process (`TestClient(api.main.app)`), writes `{"body": <snapshot>}` with sorted keys, prints episode count and byte size; exits 2 if size > 3,000,000 bytes.
- Precondition: `modal-p200-t12-20261108` is `completed` and published (check `modal run modal_app/world_runner.py --action status`; if its doc lacks task items run `--action publish` after Task 1 is deployed in the mounted code).

- [ ] **Step 1:** Write the script; run it for `modal-p200-t12-20261108`. Expected: `2400 episodes`, size < 3 MB.
- [ ] **Step 2:** Inspect: no review text, no secrets, no URLs (`grep -c "http" file` → 0).
- [ ] **Step 3:** Add to `generate-samples.mjs`, run `npm run generate:samples` (or the script name in `web/package.json`), confirm `samples.json` contains `world_generation_snapshot`.
- [ ] **Step 4:** Commit `data: real 2,400-episode sample snapshot (scripted run modal-p200-t12-20261108)`.

### Task 5: Frontend contract

**Files:**
- Modify: `web/src/lib/api/schemas.ts`, `web/src/lib/api/types.ts`, `web/src/lib/api/client.ts`
- Test: `web/src/lib/api/client.test.ts`

**Interfaces:**
- Produces: `generationSnapshotSchema` (Zod; `path: z.array(z.tuple([z.number().int().min(0).max(5), z.number().int()]))`), `type GenerationSnapshot = z.infer<...>`, `CrucibleApi.snapshot(generationId: string): Promise<GenerationSnapshot>` → `GET /world/generations/{id}/snapshot`; sample mode: paths ending `/snapshot` return `getSample("world_generation_snapshot").body`.

- [ ] **Step 1: Failing test** `parses the sample snapshot in sample mode`: `new CrucibleApi("http://x", "sample").snapshot("any")` resolves; `episodes.length === 2400`; `limits.sampled === false`.
- [ ] **Step 2:** `cd web && npx vitest run src/lib/api/client.test.ts` → FAIL.
- [ ] **Step 3:** Implement (check `/snapshot` before the generic `/world/generations/` sample branch).
- [ ] **Step 4:** Vitest → PASS; `npm run typecheck` → 0 errors.
- [ ] **Step 5:** Commit `feat(web): typed snapshot client`.

### Task 6: Motion engine (pure TS)

**Files:**
- Create: `web/src/components/observatory/motion.ts`
- Test: `web/src/components/observatory/motion.test.ts`

**Interfaces:**
- Consumes: `GenerationSnapshot` (Task 5).
- Produces:
  - `export const BUDGET = { MAX_SHOPPERS: 2500, MAX_PRODUCT_INSTANCES: 3000, MAX_LABELS: 40, MAX_DPR: 1.5 } as const`
  - `selectRendered(episodes: GenerationSnapshot["episodes"], max = BUDGET.MAX_SHOPPERS): number[]` — indices; all if ≤ max, else deterministic (sort by FNV-1a hash of episode id, take first `max`, return ascending).
  - `buildLayout(snapshot: GenerationSnapshot): Layout` where `Layout = { worldCenters: Float32Array /*xyz per world*/, shopOffsets: Float32Array /*xyz per category, relative*/, productSlots: Map<string /*`${world}:${product}`*/, number /*instance idx*/>, productPositions: Float32Array }` — worlds on a golden-angle spiral (spacing 9 units), shops on a ring of radius `max(3, categories.length * 0.45)` around each world; product instances only for `(world, product)` pairs present in rendered paths, capped at `MAX_PRODUCT_INSTANCES`.
  - `stopPoint(layout, world: number, stop: [number, number], out: Float32Array, o: number): void` — writes xyz.
  - `writePositions(snapshot, layout, rendered: number[], time: number, out: Float32Array): void` — time in seconds; each episode moves 1.2 s per hop with phase offset `(hash % 1000) / 1000 * pathDuration`, loops; writes xyz per rendered episode, linear interpolation between stops.

- [ ] **Step 1: Failing tests** (use the real sample snapshot from `@/generated/samples.json`):
  - `budget constants are exact` (deep-equal the object above).
  - `selectRendered caps and is deterministic`: synthetic 5,000-id array → length 2500, same result twice, ascending.
  - `selectRendered returns all when under budget`: sample (2,400) → 2,400.
  - `positions are finite and stay near their world`: `writePositions` at t=0, 3.7, 100 → no NaN; each point within `ringRadius + 4` of its world centre.
  - `product instances never exceed budget`.
- [ ] **Step 2:** `npx vitest run src/components/observatory/motion.test.ts` → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Vitest → PASS; typecheck + lint clean.
- [ ] **Step 5:** Commit `feat(web): budgeted motion engine for snapshot crowds`.

### Task 7: Perf harness route + MacBook check

**Files:**
- Create: `web/src/app/observatory/perf/page.tsx` (server: fetch snapshot of newest generation via `serverApi().snapshot`), `web/src/components/observatory/crowd-scene.tsx` (client, `next/dynamic` `ssr:false`)
- Modify: `web/src/components/observatory/observatory-store.ts` (add `time: number`, `focusWorld: number | null`, `setTime`, `setFocusWorld`; keep existing fields — `/observatory` must keep working)

**Interfaces:**
- Consumes: Tasks 5–6.
- Produces: `/observatory/perf` showing one `InstancedMesh` of rendered shoppers, one of products, one of shop shells; `dpr={[1, BUDGET.MAX_DPR]}`; `frameloop={playing ? "always" : "demand"}`; HTML overlay: "showing N of M", rolling FPS (avg over 2 s). Neutral placeholder look (Phase B restyles). `useFrame` calls `writePositions` into a reused `Float32Array`, then sets instance matrices; no per-entity React components, no `setState` per frame.

- [ ] **Step 1:** Implement; `npm run typecheck && npm run lint && npm test` → all pass (existing 25 tests + new).
- [ ] **Step 2:** `NEXT_PUBLIC_DATA_MODE=sample NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000 npm run build && npm start`; open `/observatory/perf` in Chrome on the MacBook; record FPS after 10 s at default zoom. Pass: ≥ 45 fps, "showing 2400 of 2400". Also confirm `/observatory` still renders.
- [ ] **Step 3:** Append measured FPS + machine to `DECISIONS.md`.
- [ ] **Step 4:** Commit `feat(web): /observatory/perf harness — 2,400 shoppers within budget`.

---

## Self-review notes

- Spec coverage: snapshot contract (T2–3), caps (T2, T6), per-world task facts (T1), real data sample (T4), Zod (T5), instanced/budget/demand frameloop (T6–7), FPS acceptance (T7). Phase B (look, HUD, world view fly-to, labels, kill-rule registry from data, removing "Qwen Shopper 03") intentionally excluded.
- Task 4 depends on the Modal run finishing; Tasks 5–7 can use a temporary local snapshot exported from `rc-real-20261102` until then, but the committed sample must be the 2,400-episode run.
