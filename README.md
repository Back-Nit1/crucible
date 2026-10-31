# Crucible

Evolutionary RL world that trains open models to shop on PayPal (sandbox). Spec: [`prompt.md`](prompt.md).
Architecture: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). Decisions: [`DECISIONS.md`](DECISIONS.md).
Platform status / contracts: [`docs/handoffs/platform-status.md`](docs/handoffs/platform-status.md).
Day-1 evidence: [`docs/spikes/platform-day1.md`](docs/spikes/platform-day1.md).

## Setup
```
uv sync
cp .env.example .env     # fill in sandbox credentials only; .env is git-ignored, never commit it
UV_CACHE_DIR=/tmp/crucible-platform-uv uv run pytest -q          # default: mock backend, no network
uv run uvicorn api.main:app --reload                              # API on :8000
```
Env names (all blank in `.env.example`): `PAYPAL_CLIENT_ID/SECRET/ENV(sandbox)`, `PAYPAL_SANDBOX_BUYER_EMAIL/PASSWORD`,
`KERNEL_API_KEY`, `MODAL_TOKEN_ID/SECRET`, `ELASTIC_CLOUD_ID` (or `ELASTIC_ENDPOINT`) + `ELASTIC_API_KEY`,
`CHANNEL3_API_KEY`, `BESTBUY_API_KEY` (Best Buy is disabled), `ZAPIER_WEBHOOK_URL`. API: `PAYMENTS_BACKEND=sandbox` selects live PayPal sandbox.

## Reproducible commands
```
uv run pytest -q -m live tests/test_payments_live.py                                  # live PayPal sandbox (needs creds in env)
uv run python -m scripts.day1_live --env-file .env channel3 --max-credits 20          # Channel3 probe (<=20 credits)
uv run python -m scripts.day1_live --env-file .env elastic --category Video_Games --drop   # disposable spike_* indices
uv run python -m scripts.build_snapshot --category Sports_and_Outdoors --index --env-file .env   # snapshot + manifest
uv run modal run modal_app/day1_probe.py::checkpoint_resume_probe                     # Modal Volume resume proof
```
Postman: import `postman/crucible.postman_collection.json` + `postman/crucible.postman_environment.json` (secrets are blank placeholders).

## Infrastructure status
| Service | Status |
|---|---|
| PayPal Orders v2 sandbox | OAuth, create, get, idempotent replay, pre-approval capture rejection live-verified. Approval + capture **not** run (no buyer account). |
| Kernel approval | Code + probe done; login challenge unknown until buyer credentials exist. **Blocked** (no `PAYPAL_SANDBOX_BUYER_*`). |
| PayPal Agent Toolkit | Not used: required actions not confirmed. |
| Elastic Serverless | Connected; mappings, keyword/vector/hybrid verified (see spike). Embeddings: `.jina-embeddings-v5-text-nano` (768d). |
| Channel3 | Live product display only; no review text; snapshot/training barred by ToS. Opt-in. |
| Best Buy | Disabled (signup unavailable). |
| Modal | Auth OK; Volume resume proven. GPU functions blocked: workspace needs a payment method. $0 spent. |
| Qwen tool-call probe | **Not measured** (needs Modal GPU). |
| Frozen snapshot | 590 products / 14,541 reviews in 4 categories; complete enumeration and review-id lookup; stable composite review ids. |
| Memory + checkpoints | `TraceMemoryProvider` (Elastic or in-memory) enforces no test/held-out/killed retrieval; atomic resumable `CheckpointStore`. |
| Quotes | All-in `Quote` enforced before order creation; snapshot quotes are disclosed as `snapshot_declared`. |
| Pipeline | Real-snapshot tasks (`data/tasks/tasks_v1.json`), scripted-shopper episode and one resumable generation verified live (scripted, not a model). |
| Astropods / Render / Zapier | Not built. |

More commands (see `docs/handoffs/integration-runtime.md`):
```
uv run python -m scripts.generate_tasks --env-file .env
uv run python -m scripts.live_episode --env-file .env
uv run python -m scripts.run_generation --env-file .env
```

## Explicitly incomplete
Qwen tool-calling metrics (Modal needs a payment method); Kernel buyer approval and capture timings; Modal GPU/LoRA cost measurement; APIMatic plugin install;
Astropods deploy; web UI. Amazon data has no stock or size availability: those constraints are unverifiable and must not be generated.
