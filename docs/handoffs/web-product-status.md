# Web product status — `feat/web-product`

Base: `feat/operational-world` at `2ffefc888c0a64de8bafc3b97bb23f34cb92b47e`.
Agent 1's `feat/release-convergence` head `c79feee` was merged exactly once in `3777f2c`.
Latest verified implementation before this documentation commit: `ce12a4b`.
No external deployment or paid infrastructure was created.

## Delivered routes

| Route | Delivered behavior |
|---|---|
| `/` | Typed buyer runs, parsed intent, explicit assumptions/unknowns, research replay, product provenance, review-ID evidence, comparison, honest no-match, quote freshness/breakdown, deliberate confirmation, approval status, receipt, and recoverable errors |
| `/world` | Generation metrics with denominators, scripted/model provenance, fitness, kills, task mix, curation, checkpoint identity, leaderboard, and rule registry |
| `/world/generations` | Generation archive |
| `/world/generations/[id]` | Population, lineage, survivor selection, task mix, checkpoint, Loophole Hunter proposals, and curation manifest |
| `/world/safety` | Versioned kill rules, evidence, co-fired rules, and proposal/confirmation state |
| `/episodes` | AG Grid infinite row model with API offset/limit, supported server sorting/filtering, pinned columns, pagination, and CSV export |
| `/episodes/[id]` | Task, complete ordered replay, score/gate, kills/evidence, genome/memory settings, payment events, and model/prompt/catalog provenance |
| `/models` | Checkpoint registry, contender comparability, held-out metrics, variance/latency/cost, and explicit not-run/not-measured states |
| `/payments` | AG Grid mock/sandbox ledger; production mode is rejected by schema |
| `/system` | Health/readiness, public redacted config, provider/payment labels, catalog provenance, data mode, refresh time, and actionable degradation |

## Buyer contract convergence

The web client now consumes the API-owned event stream directly:

- `POST /agent/runs` starts an idempotent buyer run;
- `GET /agent/runs/{id}?after={seq}` supports bounded polling and event merging;
- `POST /agent/runs/{id}/confirm` is the only checkout capture path;
- discriminated events cover intent, assumptions/unknowns, research, product cards, review citations, comparison, no-match, quote, confirmation request, approval, receipt, and typed errors;
- product and review provenance, canonical review IDs, stock/size unknowns, quote basis/components/freshness, budget verdict, and mock/sandbox mode are rendered without inference;
- recommendation selection and capture authorization are separate interactions;
- `model_unavailable` remains a typed unavailable state and never falls back to simulated output.

The event schemas are isolated in `web/src/lib/api/schemas.ts`; the client boundary is in `web/src/lib/api/client.ts`. Sanitized fixtures are regenerated from `docs/api/samples` with `npm run generate:samples`.

## Data modes

- **Live:** validates responses from `NEXT_PUBLIC_API_BASE_URL`. Operational server pages render per request; AG Grid and buyer interactions use the same typed client.
- **Sample:** visibly labelled on every route. It replays the API's sanitized buyer recommendation, no-match, and receipt fixtures without network calls or payment activity. Other writes fail closed.
- `NEXT_PUBLIC_API_BASE_URL` and `NEXT_PUBLIC_DATA_MODE` are the only browser environment values. The production bundle was scanned for common credential patterns; no match was found.

## API contracts consumed

`GET /health`, `/ready`, `/config`, `/world/generations`, `/world/generations/{id}`, `/world/episodes`, `/world/episodes/{id}`, `/world/leaderboard`, `/world/kills`, `/world/kill-rules`, `/models/evaluations`, `/models/checkpoints`, `/payments/ledger`, `/agent/runs/{id}`; `POST /agent/runs`, `/agent/runs/{id}/confirm`.

All responses cross Zod schemas. Errors use `{"error":{"code","message"}}`. Unsupported values render **Not exposed**, **Not measured**, **Not run**, or **unknown**, never an inferred zero.

## Screenshots

- [Buyer agent](../../web/docs/screenshots/agent.png)
- [World](../../web/docs/screenshots/world.png)
- [Episodes](../../web/docs/screenshots/episodes.png)
- [Models](../../web/docs/screenshots/models.png)

These are sample-mode artifacts and visibly say **Sample data**.

## Verification

| Check | Result |
|---|---|
| `npm run lint` | pass, 0 warnings |
| `npm run typecheck` | pass, strict TypeScript |
| `npm test` | 19 passed in 9 files |
| `npm run build` | pass, Next 16 production Webpack build |
| `npm run test:e2e` | 6 passed, 2 intentional project-specific skips; desktop checkout plus desktop/Pixel 7 route and keyboard coverage |
| Built-asset credential-pattern scan | clean |
| `npm audit --omit=dev` | 0 production vulnerabilities |
| Python API contract tests | 40 passed; one existing Starlette/httpx deprecation warning |

Python contract command:

```bash
UV_PROJECT_ENVIRONMENT=/Users/nityanthmaramreddy/Downloads/Crucible-runtime/.venv \
UV_CACHE_DIR=/tmp/crucible-web-uv \
uv run pytest -q tests/test_api.py tests/test_api_endpoints.py tests/test_api_world.py tests/test_api_buyer.py
```

Accessibility evidence: semantic landmarks/headings/tables/labels, skip link, visible focus, keyboard dialog controls, color-independent badge text, explicit unknown/error text, mobile navigation opened by keyboard, and desktop/mobile Playwright coverage. Playwright concurrency is bounded to two workers for stable Next/AG Grid execution on constrained runners.

## Remaining platform contracts

1. Configure CORS for the deployed web origin, or provide a same-origin proxy. Cross-origin behavior is not yet deployed or verified.
2. Add list-level episode fields for `is_impossible`, grounding verdict, latency, model/checkpoint identity, and purchase/no-match outcome if judges need direct grid filters. The UI does not infer them.
3. Add episode-detail ground-truth constraints, retrieved-memory provenance (without shopper PII), raw-output hash, quote breakdown, idempotency result, and sanitized receipt fields when available.
4. Add generation numerators/denominators for review grounding, wrong refusals, review-trap accuracy, feasible/impossible outcomes, latency/cost, model/prompt/judge versions, and checkpoint resume events.
5. Keep the published evaluation/checkpoint document shape stable: contender/model/checkpoint versions, manifest/task/catalog hashes, seed set, per-metric numerator/denominator/excluded/value, variance, judge version, latency, and cost.
6. Extend the ledger with currency, event status/time, proposal/confirmation, order/capture identifiers or typed references, idempotency result, latency, and sanitized error codes.
7. Expose scheduler status and catalog manifest on the public system contract if they should appear independently of generation records.

## Honest blockers

- The bounded Qwen probe is `blocked_not_run`: Modal launch authorization confirmations are absent; recorded GPU spend is `$0`, and no model metrics exist.
- The default buyer endpoint returns typed `model_unavailable` unless an authorized model adapter is configured.
- PayPal sandbox approval/capture remains blocked on sandbox buyer credentials; population/world runs must continue using MockPayments.
- Evaluation and checkpoint sample APIs are empty, so Models correctly displays **Not run** / **No checkpoints registered**.
- API and web services are not deployed; CORS/same-origin routing has not been exercised.
- AG Grid Community supplies the dense explorer, pinned columns, filters, pagination, and CSV. Enterprise-only row grouping/master-detail was not added without a licensed dependency; audited episode detail uses a dedicated route.

## Deployment

`render.yaml` contains a free Node web service rooted at `web/`:

1. Set public `NEXT_PUBLIC_API_BASE_URL` before building and use `NEXT_PUBLIC_DATA_MODE=live` for judge deployment.
2. Render runs `npm ci && npm run build`, then `npm start -- --hostname 0.0.0.0 --port $PORT`.
3. Configure no server credential in the web service. Elastic, PayPal, Modal, Kernel, and provider secrets remain API-side.
4. Verify `/`, `/system`, one generation detail, one episode detail, `model_unavailable`, no-match, quote expiry, PayPal approval-required, and capture failure from a clean browser.

## Branch commits

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
1e435ca docs(web): record product convergence handoff
3777f2c merge: converge web product with release runtime
e156e37 feat(web-agent): consume typed buyer event contract
5f07ff5 test(web-agent): cover converged confirmation flow
ce12a4b fix(web-agent): contain long provenance references
```
