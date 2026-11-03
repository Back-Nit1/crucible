# Deployment foundation

Nothing here spends money by itself: the Render blueprint is `plan: free`, Modal world runs are CPU-only at about
$0.002 per 24-episode generation, and **no recurring Modal schedule exists unless `CRUCIBLE_ENABLE_SCHEDULE=1` is set at deploy time**.

## Services
| Service | Where | Start | Health |
|---|---|---|---|
| `crucible-api` (FastAPI) | Render (free) via `render.yaml` | `uv run uvicorn api.main:app --host 0.0.0.0 --port $PORT` | `GET /health` (liveness), `GET /ready` (configured backends, booleans only) |
| world runner | Modal app `crucible-world` | `modal run modal_app/world_runner.py --action run ...` | `--action status` |
| `crucible-web` (Next.js) | Render (free) via `render.yaml`, `rootDir: web` | `npm start -- --hostname 0.0.0.0 --port $PORT` | `GET /` |

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
| `DEMO_MODE` | no | api | `1` = safe demo defaults; hides third-party brand names in catalog routes and buyer events (`api/masking.py`; text only, free-text mentions without a `brand` field are not detected) |
| `CORS_ALLOW_ORIGINS` | no | api | comma list of web origins; unset = no CORS headers |
| `PAYPAL_RETURN_URL` / `PAYPAL_CANCEL_URL` | no | api | where PayPal sends the buyer after approve/cancel; set to the web app (`https://<web>/payments`, `https://<web>/`). Unset = example.com placeholders |
| `CRUCIBLE_MODEL_BACKEND` | no | api | `qwen` attaches the Modal Qwen endpoint **only if** the human-set `CRUCIBLE_MODAL_*` gates also exist; unset = typed 503 `model_unavailable` |
| `NEXT_PUBLIC_API_BASE_URL`, `NEXT_PUBLIC_DATA_MODE` | no | web (build time) | API origin; `live` or `sample`. The build fails without the first, and changing it needs a rebuild |
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

## Render runbook (free plan; the `render` CLI is not installed here, so this is manual)
Nothing below creates a paid resource. Both services are `plan: free` in `render.yaml`.
1. Render dashboard -> **New +** -> **Blueprint** -> connect GitHub `Back-Nit1/crucible`, branch `main` -> Render reads `render.yaml` and lists `crucible-api` and `crucible-web`.
2. When prompted for the `sync: false` values, paste (from your local `.env`, never into git): `ELASTIC_API_KEY`, `ELASTIC_ENDPOINT` (or `ELASTIC_CLOUD_ID`), `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`. Leave `CHANNEL3_API_KEY`, `CRUCIBLE_MODEL_BACKEND`, `MODAL_TOKEN_*` empty unless you decided to enable them. Leave `NEXT_PUBLIC_API_BASE_URL`, `CORS_ALLOW_ORIGINS`, `PAYPAL_RETURN_URL`, `PAYPAL_CANCEL_URL` empty for now (they need the other service's URL). Create the Blueprint.
3. When both services have URLs (`https://crucible-api.onrender.com`, `https://crucible-web.onrender.com`, unless Render added a suffix because the name was taken), set:
   - `crucible-web` -> Environment: `NEXT_PUBLIC_API_BASE_URL` = the API URL (no trailing slash). It is read at **build** time: trigger **Manual Deploy -> Clear build cache & deploy**.
   - `crucible-api` -> Environment: `CORS_ALLOW_ORIGINS` = the web URL, `PAYPAL_RETURN_URL` = `<web URL>/payments`, `PAYPAL_CANCEL_URL` = `<web URL>/`. Saving redeploys the API.
4. Verify (first request after idle takes ~30-60 s on the free plan):
   ```
   uv run python -m scripts.verify_deploy https://crucible-web.onrender.com https://crucible-api.onrender.com
   ```
   Exit 0 and `11/11 checks passed` is the bar. It checks health/ready/config, web routes, a real generation and episode detail, the CORS preflight, the typed `model_unavailable` path (skipped, not called, if a model is configured so it cannot spend) and scans the web bundle for secret-shaped strings.
5. Sandbox checkout: judges approve in PayPal's own page using the sandbox buyer login; PayPal then returns them to `<web>/payments`. The ledger behind `/payments/ledger` lives in API memory and resets when the free service restarts or sleeps; PayPal keeps the real sandbox records.
6. Keep-alive (documented, free): create a free HTTP monitor (for example UptimeRobot, 10-minute interval, GET) on `https://crucible-api.onrender.com/health` and one on `https://crucible-web.onrender.com/`. Render free web services sleep after idle; the pings keep them warm for the judging window. Remove the monitors afterwards. The API `/health` touches no dependency.
7. Known gap: the API must run from the repository checkout (it reads `config/providers.yaml` and `data/manifests/`, which are not in the installed package). `render.yaml` does this (`uv sync` + `uv run uvicorn` from the repo root); do not switch to `pip install .` + a console script.
