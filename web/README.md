# Crucible web product

Judge-facing and buyer-facing Next.js application for the operational Crucible API.

## Local setup

```bash
cd web
cp .env.example .env.local
npm ci
npm run dev
```

`NEXT_PUBLIC_API_BASE_URL` is the public origin of the FastAPI service, without a trailing path. `NEXT_PUBLIC_DATA_MODE` is either:

- `live`: call the configured API and validate every response;
- `sample`: replay the sanitized envelopes generated from `../docs/api/samples`.

Sample mode is visibly labelled on every surface, rejects mutating requests, and never simulates model output. Regenerate the checked-in sample bundle after API sample changes with `npm run generate:samples`.

Never put Elastic, PayPal, Modal, Kernel, Channel3, Best Buy, sandbox buyer, or other server credentials in a `NEXT_PUBLIC_*` variable. Next.js embeds public variables into browser assets at build time.

## Routes

| Route | Purpose |
|---|---|
| `/` | Buyer agent, grounded research, no-match, quote and explicit confirmation boundary |
| `/world` | Operational generation summary and provenance |
| `/world/generations` | Generation archive |
| `/world/generations/[id]` | Population, lineage, mutations, checkpoint, loopholes, curation |
| `/world/safety` | Kill-rule registry, evidence, co-fired rules, Loophole Hunter proposals |
| `/episodes` | AG Grid server-filtered episode explorer |
| `/episodes/[id]` | Ordered replay, score, kills, provenance, payment events |
| `/models` | Checkpoint registry and held-out contender evaluations |
| `/payments` | Mock/sandbox ledger only |
| `/system` | Public health, readiness, redacted config, and catalog provenance |

## Verification

```bash
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 NEXT_PUBLIC_DATA_MODE=sample npm run lint
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 NEXT_PUBLIC_DATA_MODE=sample npm run typecheck
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 NEXT_PUBLIC_DATA_MODE=sample npm test
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 NEXT_PUBLIC_DATA_MODE=sample npm run build
npx playwright install chromium  # once per machine
npm run test:e2e
```

The build uses Next's supported Webpack path because Turbopack's PostCSS worker cannot bind its internal port in the managed macOS sandbox. Production dependencies have zero known audit findings (`npm audit --omit=dev`).

## Live API prerequisites

- The API must allow the web origin through CORS, or both services must be placed behind a same-origin proxy.
- `/agent/run` must return purchase context before the quote button can be enabled: task ID, agent ID, verified budget cap, and selected variant.
- The current product pick contract omits category, stock, size, caveats, and all-in quote data; the UI renders those fields as unknown.
- `NEXT_PUBLIC_API_BASE_URL` is frozen into client assets during `npm run build`, so set it before the Render build begins.
