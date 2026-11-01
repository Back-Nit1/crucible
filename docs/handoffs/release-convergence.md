# Release convergence (Agent 1) — branch `feat/release-convergence`

Base: `feat/operational-world` @ `2ffefc8` (canonical). Model source: `feat/model-training-product` @ `931352f` (based on
`feat/integration-runtime` `9e01481`). Not merged: `feat/core-generation` (superseded), `feat/scoring-contracts` (old).
Final head: see `git log -1` on this branch (last commit before this doc: `fix(world): count killed refusals...`).
Nothing merged to `main`, nothing deployed.

## Status: built / live-verified / blocked / unimplemented
| Area | State |
|---|---|
| Model-branch port (adapter, batch, review signals, judge, curation/planning, eval comparison) | **built**, tested |
| One generation path (`world.runtime`, scripted or model-backed, memory, resume, breaker) | **built**, tested; scripted path **live-verified** on the real snapshot |
| `QwenInferenceClient` (`agents/qwen_client.py`, `modal_app/qwen_inference.py`) | **built**, tested with injected transport only; **never run against Modal** |
| Bounded 20-prompt Qwen probe (`scripts/qwen_probe.py`) | **built**; **BLOCKED, not run**: GPU spend `$0` |
| Base-Qwen / memory real-snapshot generations | **not run** (gated on the probe passing) |
| Buyer API contract (`/agent/runs`, poll, confirm; `/agent/run`) | **built**, tested with scripted model double; OpenAPI + samples published |
| PayPal sandbox + Kernel live check | **BLOCKED**: missing `PAYPAL_SANDBOX_BUYER_EMAIL`, `PAYPAL_SANDBOX_BUYER_PASSWORD` in the env file |
| `/models/evaluations`, `/models/checkpoints` | **live-verified** plumbing (disposable index); real `qwen-base` checkpoint record published; **0 evaluation records** (no measured model run exists) |
| Training / LoRA | planning + curation only; **unimplemented** (no trainer, no survivor Qwen traces) |
| Frontend (`web/`) | **unimplemented** (out of scope here) |

## Reconciliation decisions
- **Canonical wins.** `FrozenCatalogProvider` (`iter_products(category, manifest_hash)`, `get_review_ids`), namespaced review ids,
  `TraceRecord` v2, `RepositoryMemoryProvider`, `GenerationStore`, `Quote`/`GuardedPayments` untouched in contract.
- **`agents/grounding.py` not ported**: `get_review_ids(...).ids` already gives complete product-scoped ids; model-side
  `SnapshotCatalog` / `review_count` do not exist here. `tasks/review_signals.py` and `tasks/batch.py` were rewritten onto
  `FrozenCatalogProvider` (batch takes per-category `manifests`; manifest records `category_manifest_hashes`).
- **`world/orchestrator.py` not ported** (parallel orchestration, second checkpoint store). Its useful parts live in
  `world.runtime` (`PolicyFactory`, model policy) and `world.report` (`rates` with numerator/denominator, `model_usage`).
- `Compat.policy_id` added: a scripted checkpoint cannot be resumed by a model run (and vice versa).
- `world.taskgen` review traps now carry **automated-verified** signals (required by the stricter `build_review_trap`).
- Scripted traces (`model_checkpoint` starts with `scripted`) are **never retrievable as memory** (they read the answer key).
- `PendingOrder` keeps its verified `Quote`; `confirm_and_pay` now raises `QuoteStale` if the buyer-seen quote expired.
- `pyproject` was missing `catalog.sources` (packaging bug) — fixed; `tests/test_packaging.py` guards it.
- Model-branch test files: all 10 ported; `test_world_orchestrator.py` replaced by `test_world_model_generation.py`.
- Generation CLI is the single entry point (`scripts/run_generation.py`; `modal_app/world_runner.py` drives the same runtime).

## Tests (exact)
`uv run pytest -q` -> **294 passed, 5 deselected** (live). Baseline was 209 passed / 4 deselected; no test file deleted.
`pytest -m live` with `ELASTIC_*` only: **3 passed** (trace round trip, frozen catalog vs manifests, models endpoints round trip),
**2 skipped** (PayPal: no sandbox credentials). Secret scan with the real env file: 0 findings over 212 tracked files.

## Operational run metrics (pipeline evidence, NOT model performance — scripted shoppers read the reference answer)
| | fixture `fixture-rc-91` (synthetic products) | real snapshot `rc-real-20261102` |
|---|---|---|
| tasks | 6 (4 feasible, 2 impossible, 2 review-sensitive) | 12 (9 / 3 / 2) |
| episodes expected / traced / scored | 48 / 48 / 46 | 96 / 96 / 91 |
| terminations | success 18, no_match 14, instant_kill 16 | success 40, no_match 21, instant_kill 35 |
| kills | K001 6, K002 8, K003 2, K004 10, K008 4 | K001 12, K002 18, K003 5, K004 21, K008 9 |
| hallucinated purchases / budget violations charged | 0 / 0 (2 attempts blocked) | 0 / 0 (5 blocked) |
| correct no-match on impossible | 14/16 | 21/24 |
| wrong refusal (incl. killed) | 8/32 | 18/72 |
| review grounding | 46/46 | 91/91 |
| survivors / SFT records | 3 / 18 | 3 / 30 |
Real run: interrupted at 40, resumed 56; audit `expected 96 = stored 96 = unique 96`, 0 duplicates/missing; rerun of the
completed id executed 0 episodes; a fresh offline rerun reproduced `summary.json`, `summary.md`, `training_manifest.json` byte-for-byte.
Elastic reads ~565 calls per full run. MockPayments only (`world.runtime` constructs `MockPayments()`; no sandbox import).

## Qwen probe — not measured
Blocker (exact): no Modal launch authorization. Missing: `CRUCIBLE_MODAL_TOKEN_ROTATED=1`, `CRUCIBLE_MODAL_BILLING_CONFIRMED=1`,
`CRUCIBLE_MODAL_APPROVED_CEILING_USD=<amount>`; also the workspace needs a payment method (earlier: "Please add a payment method to use L4
GPU functions"). Ceiling on record: `$0.861948` (45 min L4+2 CPU+32 GiB); not raised. Artifact: `docs/spikes/results/qwen_probe.{json,md}`
(`blocked_not_run`). No latency/token/cost/parse-failure numbers exist; Qwen is **not** production ready, and nothing here claims it.
Pass bar (proposed in this branch, no earlier numeric bar existed — confirm it): valid call >= 90%/20, schema-valid >= 90%, parse_intent first >= 90%.
The probe is first-turn only; no-match behavior and grounding are measured by the later generation step.

## External spend
Modal GPU `$0`. PayPal `$0` (no sandbox call made). Elastic Serverless: reads + one generation of traces (96 docs), generation/kill-rule
docs, 1 checkpoint doc, disposable live-test indices (deleted).

## Remaining blockers
1. Modal: rotate token, add payment method, deploy `modal_app/qwen_inference.py` with `CRUCIBLE_ENABLE_L4_PROBE=1`, set the 3 variables, approve ceiling.
2. PayPal: add `PAYPAL_SANDBOX_BUYER_EMAIL` / `PAYPAL_SANDBOX_BUYER_PASSWORD` to the env file.
3. Review-signal extraction with a fixed model + sampled human review (only the lexical baseline exists).
4. 5 protected-split feasible-set overlaps in the broad-category tasks (see model-branch notes) before held-out evaluation.
5. Confirm the probe pass bar. 6. Packaged installs lack `config/providers.yaml` and `data/manifests` (deploy runs from the checkout).

## Reproduce
```
export UV_CACHE_DIR=/tmp/crucible-convergence-uv
uv sync && uv run pytest -q
uv run python -m scripts.run_generation --provider synthetic --traces memory --seed 91 --population 8 --tasks 6 --generation-id fixture-rc-91
uv run python -m scripts.run_generation --env-file <.env> --provider elastic_snapshot --model scripted --payments mock --seed 20261102 --population 8 --tasks 12 --generation-id rc-real-20261102   # --interrupt-after 40, rerun to resume
uv run python -m scripts.audit_traces --env-file <.env> --generation-id rc-real-20261102 --checkpoint-dir checkpoints/generations
uv run python -m scripts.secret_scan --env-file <.env>
uv run python -m scripts.paypal_live_check --env-file <.env>        # exits 3 naming missing variables
uv run python -m scripts.qwen_probe --env-file <.env>               # exits 3 until authorized
uv run python -m scripts.run_generation ... --model qwen --memory off|on   # identical task/seed pair, after the probe passes
uv run python -m scripts.publish_models --env-file <.env>           # base checkpoint record
uv run python -m scripts.export_buyer_samples                       # OpenAPI + buyer samples (offline)
uv run pytest -m live                                               # needs ELASTIC_* in the environment
```

## Frontend-facing API changes
New (see `docs/api/openapi.json`, `docs/api/samples/agent_*.json`): `POST /agent/runs` (idempotent on `request_id`), `GET /agent/runs/{id}?after=SEQ`
(poll, monotonic `seq`, `next_seq`), `POST /agent/runs/{id}/confirm` (only path to payment, needs `user_confirmed: true`).
Events (discriminated by `type`): `intent_parsed`, `assumptions`, `research`, `product_card`, `review_citation`, `comparison`, `no_match`, `quote`,
`confirmation_request`, `paypal_approval`, `receipt`, `error` (`code`, `retryable`, `action`). Run `status`: running | awaiting_confirmation | completed | failed.
Every product/review has provenance; stock/size/shipping/tax are `unknown`/`null`, never zero; quote has `basis`, `expires_at`, `fresh`,
`budget_checked_on`. Errors: `model_unavailable` (503), `quote_stale`/`quote_changed`/`budget_exceeded` (409), `confirmation_required` (428),
`payment_failed` (402, issue code in `message`). `/agent/run` is unchanged in shape (adds optional `run_id`, `status`), backed by the same runner;
without a configured model it returns 503 `model_unavailable`. `/models/checkpoints` now returns the `qwen-base` record.
