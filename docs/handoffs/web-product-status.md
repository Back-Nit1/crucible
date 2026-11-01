# Web product status — `feat/web-product`

Base: `feat/operational-world` at `2ffefc888c0a64de8bafc3b97bb23f34cb92b47e`.
Latest verified implementation head before this handoff: `ada07d12a660a8827cda07191715b4d501ea4f56`.
No external deployment was created.

## Delivered routes

| Route | Delivered behavior |
|---|---|
| `/` | Buyer request, parsed intent, assumptions, unknown/uncheckable warnings, ordered research, grounded picks/review IDs, honest no-match, quote boundary, deliberate confirmation dialog, sandbox receipt and recoverable errors |
| `/world` | Generation metrics with denominators, scripted/model provenance, fitness, kills, task mix, curation, checkpoint identity, leaderboard, rule registry |
| `/world/generations` | Generation archive |
| `/world/generations/[id]` | Population, founder/child lineage, survivor/next-population selection, task mix, checkpoint, Loophole Hunter proposals, curation manifest |
| `/world/safety` | Versioned kill rules, kill evidence, co-fired rules, proposal/confirmation state |
| `/episodes` | AG Grid infinite row model with API offset/limit, supported server sorting/filtering, pinned columns, pagination, CSV export |
| `/episodes/[id]` | Task, parsed intent, complete ordered replay, arguments/references, score/gate, kills/evidence, genome/memory settings, payment events, model/prompt/catalog provenance |
| `/models` | Checkpoint registry, contender comparability, held-out metrics, variance/latency/cost, explicit not-run/not-measured states |
| `/payments` | AG Grid mock/sandbox ledger; production mode rejected by schema |
| `/system` | Health/readiness, public redacted config, provider/payment labels, catalog manifest, data mode, refresh time, actionable degradation |

## Data modes

- **Live:** validates responses from `NEXT_PUBLIC_API_BASE_URL`. Operational server pages render per request; the episode grid and buyer agent call the same typed boundary from the browser.
- **Sample:** generated only from `docs/api/samples/*.json`; visibly labelled on every route; mutating requests fail with `sample_read_only`; model output is never simulated. The buyer page shows the sanitized no-match episode replay.
- `NEXT_PUBLIC_API_BASE_URL` and `NEXT_PUBLIC_DATA_MODE` are the only browser environment values. The production bundle was scanned for server credential names and common key patterns; no matches were found.

## API contracts consumed

`GET /health`, `/ready`, `/config`, `/world/generations`, `/world/generations/{id}`, `/world/episodes`, `/world/episodes/{id}`, `/world/leaderboard`, `/world/kills`, `/world/kill-rules`, `/models/evaluations`, `/models/checkpoints`, `/payments/ledger`; `POST /agent/run`, `/purchase/propose`, `/purchase/confirm`.

All responses cross Zod schemas. Errors use `{"error":{"code","message"}}`. Unsupported fields render **Not exposed**, **Not measured**, **Not run**, or **unknown** rather than a zero or inferred value.

## Screenshots

- [Buyer agent](../../web/docs/screenshots/agent.png)
- [World](../../web/docs/screenshots/world.png)
- [Episodes](../../web/docs/screenshots/episodes.png)
- [Models](../../web/docs/screenshots/models.png)

These are sample-mode artifacts and visibly say **Sample data**.

## Verification

Run from `web/` with `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 NEXT_PUBLIC_DATA_MODE=sample`:

| Check | Result |
|---|---|
| `npm run lint` | pass, 0 warnings |
| `npm run typecheck` | pass, strict TypeScript |
| `npm test` | 19 passed in 9 files |
| `npm run build` | pass, Next 16 production Webpack build; operational routes dynamic |
| `npm run test:e2e` | 5 passed, 1 intentional desktop skip; desktop + Pixel 7 projects |
| Built-asset secret scan | clean |
| `npm audit --omit=dev` | 0 production vulnerabilities |
| Python API contract tests | 22 passed; one existing Starlette/httpx deprecation warning |

Python command:

```bash
UV_PROJECT_ENVIRONMENT=/Users/nityanthmaramreddy/Downloads/Crucible-runtime/.venv \
UV_CACHE_DIR=/tmp/crucible-web-uv \
uv run pytest -q tests/test_api.py tests/test_api_endpoints.py tests/test_api_world.py
```

Accessibility evidence: semantic landmarks/headings/tables/labels, skip link, visible focus, keyboard dialog controls, color-independent badge text, mobile navigation opened by keyboard, desktop/mobile Playwright coverage, ESLint JSX accessibility rules. Responsive artifacts were captured at desktop; the Pixel 7 route suite passed.

## Backend contracts required from Agent 1

1. Configure CORS for the deployed web origin, or provide a same-origin proxy. The current browser client targets the public API origin directly.
2. Extend `AgentRunResult` with an opaque purchase context: `task_id`, `agent_id`, verified `budget_cap`, and variant identifier. Until all are present, quote creation intentionally remains disabled.
3. Extend picks with category, price basis, explicit stock/size state (`available`, `unavailable`, `unknown`), matched constraints, caveats, and source product ID. The UI currently shows omitted values as unknown.
4. Extend quote responses with subtotal, shipping, tax, discounts, total, currency, `as_of`, and `expires_at`. Current quote expiry is displayed as unavailable.
5. Publish explicit buyer checkout states for PayPal approval required, approved, capture failed, and completed. Never send OAuth tokens or buyer credentials.
6. Add list-level episode fields for `is_impossible`, grounding verdict, latency, model/checkpoint identity, and purchase/no-match outcome if judges must filter those columns. The UI does not infer them from review IDs or termination text.
7. Add episode-detail ground-truth constraints, retrieved-memory metadata/provenance (not shopper PII), raw-output hash, quote breakdown, idempotency result, and sanitized receipt fields.
8. Add generation summary numerators/denominators for review grounding, wrong refusals, review-trap accuracy, feasible/impossible outcomes, latency/cost, plus model/prompt/judge versions and checkpoint resume events.
9. Stabilize evaluation/checkpoint document schemas (contender, checkpoint/model versions, manifest/task/catalog hashes, seed set, per-metric numerator/denominator/excluded/value, variance, judge version, latency, cost). The current indices are empty.
10. Extend the ledger with currency, event status/time, proposal/confirmation, order/capture IDs or typed references, idempotency result, latency, and sanitized error code. The current UI labels all omitted fields unavailable.
11. Expose scheduler status and catalog manifest on the public system contract if they should appear independently of generation records.

## Honest blockers

- `/agent/run` has no configured model runner, so live buyer research returns typed `model_unavailable`.
- The buyer response lacks safe purchase context, so a real quote/capture cannot yet be initiated from a recommendation.
- PayPal sandbox approval/capture remains blocked on sandbox buyer credentials per runtime handoff.
- Evaluation and checkpoint APIs return empty pages; the Models screen correctly says **Not run** / **No checkpoints registered**.
- The API and web services have not been deployed, and cross-origin behavior is not yet verified.
- AG Grid Community provides the dense explorer, pinned columns, filters, pagination, and CSV. Enterprise-only row grouping/master-detail was not added without a licensed dependency; episode detail is a dedicated audited route.

## Deployment

`render.yaml` now contains a free Node web service rooted at `web/`:

1. Set `NEXT_PUBLIC_API_BASE_URL` to the public API origin before the build. It is public and frozen into client assets.
2. Keep `NEXT_PUBLIC_DATA_MODE=live` for the judge deployment; use `sample` only for explicitly labelled evidence replay.
3. Render runs `npm ci && npm run build`, then `npm start -- --hostname 0.0.0.0 --port $PORT`.
4. Configure no server credential in the web service. All Elastic, PayPal, Modal, Kernel, and provider secrets remain API-side.
5. Verify `/`, `/system`, a generation detail, an episode detail, and buyer `model_unavailable`/checkout flows from a clean browser before judging.

## Commit list

```text
7462cca build(web): bootstrap typed Next.js application
33c36fb chore(web): ignore TypeScript build cache
95ecb20 feat(web): add API client and validated data modes
78829ee test(web): add frontend test harness
39bcf1b feat(web): establish Crucible design system and shell
6a705ab feat(web-agent): build grounded shopping and confirmation flow
ea573b0 test(web-agent): cover no-match and explicit confirmation
58cab53 feat(web-world): add operational world dashboard
3a9afd3 feat(web-world): add generation detail and lineage
c0343c6 feat(web-episodes): add AG Grid episode explorer
f4f41d9 feat(web-episodes): add auditable replay detail
76ec233 feat(web-models): add checkpoint and evaluation views
7356d55 feat(web-safety): add kill and loophole inspection
1efbe00 feat(web-payments): add mock and sandbox ledger
75db327 feat(web-system): add readiness and configuration view
effda9f fix(web-agent): surface recoverable checkout failures
05377bc fix(web): render operational data at request time
a3a9193 test(web): verify responsive operational surfaces
ada07d1 build(web): add Render service blueprint
```
