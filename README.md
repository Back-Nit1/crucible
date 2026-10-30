# Crucible

Evolutionary RL world that trains open models to shop on PayPal (sandbox). Spec: [`prompt.md`](prompt.md).
Architecture: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). Decisions: [`DECISIONS.md`](DECISIONS.md).

## Dev
```
uv sync
uv run pytest
uv run uvicorn api.main:app --reload
```
Copy `.env.example` to `.env` (sandbox credentials only).

Status: Milestone 1 scaffold. Payments guards + mock backend tested. Everything else pending.
