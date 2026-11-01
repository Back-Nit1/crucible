# Deployment foundation

Nothing here spends money by itself: the Render blueprint is `plan: free`, Modal world runs are CPU-only at about
$0.002 per 24-episode generation, and **no recurring Modal schedule exists unless `CRUCIBLE_ENABLE_SCHEDULE=1` is set at deploy time**.

## Services
| Service | Where | Start | Health |
|---|---|---|---|
| `crucible-api` (FastAPI) | Render (free) via `render.yaml` | `uv run uvicorn api.main:app --host 0.0.0.0 --port $PORT` | `GET /health` (liveness), `GET /ready` (configured backends, booleans only) |
| world runner | Modal app `crucible-world` | `modal run modal_app/world_runner.py --action run ...` | `--action status` |
| web (Next.js) | Render, added by the web app owner | | |

Free Render services sleep when idle (cold start ~30-60 s). For the judging window keep it warm with an external ping to `/health`
every 10 minutes (any free uptime monitor); this is a documented, deliberate choice, not a hidden cost.

## Environment-variable inventory
| Name | Secret | Used by | Notes |
|---|---|---|---|
| `ELASTIC_API_KEY` | yes | api, world, modal | Serverless project API key |
| `ELASTIC_ENDPOINT` / `ELASTIC_CLOUD_ID` | no / no | api, world, modal | endpoint URL preferred; Cloud ID is decoded as a fallback |
| `PAYPAL_CLIENT_ID` / `PAYPAL_CLIENT_SECRET` | no / yes | api (sandbox checkout) | sandbox app only |
| `PAYPAL_ENV` | no | payments | must be `sandbox`; anything else aborts |
| `PAYMENTS_BACKEND` | no | api | `sandbox` for live PayPal sandbox, default mock. World runs ignore it: they are always mock |
| `REQUIRE_ALL_IN_QUOTE` | no | api | `1` refuses item-price-only quotes (live shipping/tax unknown) |
| `DEMO_MODE` | no | api `/config`, web | `1` = safe demo defaults, brand masking in the UI |
| `PAYPAL_SANDBOX_BUYER_EMAIL` / `_PASSWORD` | yes | `scripts.paypal_live_check`, Kernel approver | sandbox personal account |
| `KERNEL_API_KEY` | yes | Kernel approver | no CAPTCHA solving, no proxies |
| `MODAL_TOKEN_ID` / `MODAL_TOKEN_SECRET` | yes | Modal CLI | |
| `CHANNEL3_API_KEY` | yes | live chat (opt-in) | display only; no review text, no training use |
| `CRUCIBLE_ENV_FILE` | no | modal_app.world_runner | path to a local env file read at launch (values are never printed) |
| `CRUCIBLE_ENABLE_SCHEDULE`, `CRUCIBLE_SCHEDULE_CRON` | no | modal deploy | schedule is off unless `CRUCIBLE_ENABLE_SCHEDULE=1` (default cron `0 * * * *`) |
| `CRUCIBLE_MANIFEST_DIR` | no | remote runners | where `data/manifests` is mounted |
| `BESTBUY_API_KEY`, `ZAPIER_WEBHOOK_URL` | yes | unused / optional | Best Buy disabled |

## Commands
```
# API locally (demo-safe: mock payments)
DEMO_MODE=1 uv run uvicorn api.main:app --reload
# one world generation on Modal (idempotent; rerun the same id to resume)
CRUCIBLE_ENV_FILE=<.env> uv run modal run modal_app/world_runner.py --action run --generation-id remote-smoke --population 6 --tasks 4
CRUCIBLE_ENV_FILE=<.env> uv run modal run modal_app/world_runner.py --action status
CRUCIBLE_ENV_FILE=<.env> uv run modal run modal_app/world_runner.py --action resume       # latest unfinished
# prepare (do NOT run) the hourly resume schedule - requires your explicit go-ahead:
CRUCIBLE_ENABLE_SCHEDULE=1 CRUCIBLE_ENV_FILE=<.env> uv run modal deploy modal_app/world_runner.py
# disable it again
uv run modal app stop crucible-world
```

## Observability
Every API request logs one JSON line: `request_id`, `method`, `path` (never the query string or body), `status`, `latency_ms`,
`cost_usd` (set by agent runs). Modal runs return `cost` = wall seconds x Modal list price (approximate, Elastic excluded) and append it
to `cost.jsonl` on the Volume (`--action status` sums it).
