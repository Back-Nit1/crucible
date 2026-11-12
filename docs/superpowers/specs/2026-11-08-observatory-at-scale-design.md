# Observatory at scale — design

Date: 2026-11-08 · Project 3 of 4 (order: 1 Modal→dashboard ✅, 3 Observatory, 2 catalog, 4 editor + launch API)

## Intent

The current `/observatory` shows one scripted shopper walking one tiny network (3 shops, ~30 products, 8 agents).
The user wants the world to *look like what it is*: hundreds of Qwen shopper sessions running through many
copies of the commerce internet at once — pool → search exchange → category shops → products → checkout or
refusal — so a viewer immediately sees scale, and can then zoom into any single session and read its evidence.

It must open fast and stay smooth on the user's MacBook, and nothing about the data size may be able to
freeze the machine. "There is legitimately nothing stopping the agents from destroying my computer" is the
failure this design exists to prevent.

## Goals

1. Show every episode of a generation (target: 2,400 = 200 agents × 12 tasks; must degrade gracefully past that).
2. Two zoom levels, one scene:
   - **Internet view** — many search exchanges ("worlds"), each with its ring of category shops; shoppers
     stream between them. Counts, not labels.
   - **World view** — click/zoom into one world: its shops, products, its shoppers' paths, labels, and the
     existing mission / reward / learning HUD for a selected episode.
3. Every moving dot is a recorded episode. Path stops come from its replay steps (same mapping as today's
   `targetForStep`). Checkout/refusal is reached only when the episode actually terminated there.
4. Hard performance budget (below) enforced in code, not by hope.
5. Layout already handles 30+ categories per world, so project 2 (more Amazon 2023 categories) needs no redesign.
6. Visual overhaul: the user rejected the current look. New visual direction is shown as mockups and approved
   before the scene is built (see "Left to the builder / next step").

## Non-goals (this project)

- Live streaming while a run executes (SSE) — later; the snapshot contract is designed so deltas can be added.
- Experiment editor / launching runs — project 4.
- New catalog data — project 2.
- Semantic placement (embedding distance). Positions stay deterministic display coordinates and say so.
- Any Channel3 data in the world (ToS §7: no training use, no bulk storage). A labelled live-only layer may come later.

## Anti-goals (failure even if it "works")

- Page that downloads every episode detail (today: 200 episode rows + replay fetched per load).
- One React component / mesh / draw call per agent or product.
- Inventing motion: a dot that visits a shop its episode never touched.
- Losing the truth label: scripted runs must read `WORLD ENGINE REPLAY · NOT QWEN PERFORMANCE`.

## Constraints

- Backend stays the authority; browser reads one compact snapshot. FastAPI + Elastic as today; no new infra (no AWS).
- Next.js 16 / React 19 / R3F 9 / drei 10 / Zustand 5 / Zod 4 already installed — no new rendering libraries.
- Sample mode must work offline (static snapshot in `web/src/generated/`).
- Strict TS, zero-warning lint, existing tests keep passing.

## Decided

### Data: one snapshot per generation

`GET /world/generations/{id}/snapshot` → compact, immutable JSON, built server-side from the generation doc +
its traces. Cached in-process keyed by `(generation_id, published_at)` (a completed generation never changes).

Shape (indices instead of repeated strings):

```
{
  generation_id, published_at, scripted, policy, population_size, survivors, kills,
  categories: [{ id, name, product_count }],
  worlds:     [{ task_id, category, budget, impossible, review_trap, request }],   // one per task
  agents:     [{ id, variant, fitness, survivor, kill_rules }],
  products:   [{ id, category, mentions }],                                       // capped, most-mentioned first
  episodes:   [{ id, agent, world, path: [[kind, ref], ...], termination, killed, fitness }],
  limits:     { episodes_total, episodes_included, products_total, products_included, sampled: bool }
}
kind: 0 spawn · 1 exchange · 2 shop(ref=category idx) · 3 product(ref=product idx) · 4 checkout · 5 refusal
```

Server caps: ≤ 5,000 episodes (deterministic sample by episode id hash beyond that, `sampled: true`),
≤ 3,000 products. Target payload < 600 KB gzip at 2,400 episodes. Episode detail for the inspector is still
fetched on demand from the existing `/world/episodes/{id}` — only when the user selects one.

**Per-world task facts (my call).** Budget, impossible and review-trap flags are not in traces today, and the
HUD's current budget comes from the policy's own `parse_intent` (wrong for a model that misreads it). Fix:
`world/report.py` summary gains `tasks.items: [{id, category, max_total, impossible, review_trap}]` from the real
`TaskSpec`s. For generations published before that, `publish_existing` regenerates the task set
deterministically (`generate_tasks(seed, count)` on the same catalog), keeps it only if its task ids equal the
trace task ids, else the world shows "budget unknown". `request` = trace `task_text`.

**Shops and products (my call).** Every world's ring shows *all* catalog categories (4 today, 30+ after project 2):
visited shops lit, never-visited dim — the exchange is visibly choosing from the whole internet. A product is
placed per world, in that world's shop for its category; caps count per-world instances. `path [3, ref]` resolves
inside the episode's own world.

**World = task** (my call): a world is one shopping mission; all agents attempting it are its shoppers.
12 tasks → 12 exchanges, ~200 shoppers each. Rationale: it is the unit where "same mission, many policies,
different outcomes" is visible, and it matches how fitness is compared.

### Rendering

- One `InstancedMesh` for all shoppers, one for all products, one for shop shells. Per-frame work: one loop
  writing instance matrices from a `Float32Array`; no React state per entity, no re-render per frame.
- Motion: global replay clock (Zustand holds only `time`, `playing`, `speed`, `focusWorld`, `selected`).
  Each episode's position = interpolation along its path at `time`, with a per-episode phase offset so the
  crowd doesn't move in lockstep.
- Internet view: worlds on a deterministic spiral/grid; each world = exchange + ring of shops (ring radius
  grows with category count, works to 33). Product dots hidden; shop shells + shopper dots only.
- World view: camera flies to the focused world; its products, path lines (for selected episode), and up to
  40 text labels appear. Other worlds dim, still animate.
- Colour carries outcome: survivor/success, refusal, killed — consistent between dots and HUD.

### Performance budget (enforced constants, MacBook target)

| Item | Limit |
|---|---|
| Moving shoppers rendered | 2,500 (above: render a deterministic subset, HUD says "showing N of M") |
| Product instances | 3,000 |
| Text labels alive | 40 (focused world only) |
| Device pixel ratio | ≤ 1.5 |
| Post-processing | Bloom only, half-res, off in Internet view if FPS < 45 for 2 s |
| Frame loop | `demand` when paused; R3F stops on hidden tab |
| Network on load | 1 snapshot request; no per-episode fetches until a click |

Acceptance: 60 fps target / ≥ 45 fps floor on an M1-class MacBook Air at 2,400 episodes in Chrome; first
paint of HUD < 1 s on localhost; snapshot route < 1 s warm.

### HUD

Keep the current information (mission, reward contract, learning loop, population pipeline, timeline, truth
label) but driven by the snapshot and the focused world/episode. New: world picker list (accessible HTML twin
of the 3D scene), "showing N of M" when capped, outcome legend. Remove hard-coded "Qwen Shopper 03" — name
comes from the selected agent. Render kill-rule registry from data instead of the hard-coded failure list.

### Data at scale (decided)

A real scripted Modal generation `modal-p200-t12-20261108` (200 agents × 12 tasks = 2,400 episodes) is being run
for this. Its snapshot, produced by the Python builder, is committed as the offline sample
(`web/src/generated/observatory-snapshot.json`, product ASINs + task text only, no review text, < 3 MB raw) and is
what the browser FPS check runs against. No synthetic episodes anywhere.

### Build order

Phase A (no visual dependency): snapshot builder + endpoint + task metadata + Zod schema + store + instanced
motion engine with the budget constants. Phase B (after mockup approval): scene look, HUD layout.

## Left to the builder

- Exact spiral/ring math, camera fly-to easing, colours within the approved visual direction.
- Snapshot cache implementation detail (in-process dict is enough; generations are immutable).
- Test split, as long as: snapshot builder unit-tested against real `TraceRecord`s; Zod schema for the
  snapshot; a browser check at 2,400 episodes recording FPS.

## Next step before building

Show 2–3 visual-direction mockups (Internet view + World view) for the user to pick, then write the plan.
