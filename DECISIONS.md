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
