# Pre-submit checklist

State as of 2026-11-12 (deadline 2026-11-12 12:00 PM PT). Items are `prompt.md` section 17 first, then the official-rules items from section 2 and the milestone items from section 16. **PASS** = verified now with the evidence shown. **FAIL** = not met. **OWNER** = only the repository owner can do it. Re-check with `uv run python -m scripts.check_submission` (it fails while any `placeholder` remains).

## Definition of done (prompt.md section 17)
| # | Item | Result | Evidence / what is missing |
|---|---|---|---|
| 1 | A judge opens the hosted URL, types a raw message, sees grounded picks, completes a PayPal sandbox checkout after confirming | **FAIL** | Nothing is deployed (`render` CLI absent; runbook in [`docs/DEPLOYMENT.md`](../DEPLOYMENT.md), OWNER). The chat also needs a model: with no model endpoint it answers 503 `model_unavailable` (or `transport_error` when the Modal inference app is stopped, as now); the chat page says so and points to the purchase API. Checkout **without** a model works through the purchase API ([README Judge testing, Path A](../../README.md#judge-testing)); sandbox flow evidence [`paypal_live_check.json`](../payments/paypal_live_check.json) |
| 2 | World Dashboard: real generations, kills by reason, Loophole Hunter rules, lineage, replays (AG Grid) | **PASS** (local live mode) | [`docs/screenshots/world.png`](../screenshots/world.png), [`episodes.png`](../screenshots/episodes.png); data [`rc-real-20261102`](../runs/rc-real-20261102/summary.md). AG Grid is used on `/episodes` and `/payments` only. Hosted version: FAIL until deployed |
| 3 | Model Dashboard: base vs memory vs fine-tuned (vs ceiling), held-out tasks/categories, pass^k, WebShop, review metrics | **FAIL** | No complete evaluation: base eval is partial (86/141, 0 successes, harness fixes pending, [`STATUS.md`](../evaluations/eval-20261110-base/STATUS.md)); the page shows **Not run** where nothing was measured ([`models.png`](../screenshots/models.png)). Needs OWNER to raise the Modal ceiling (billed about $2.70 of $3.00), then [`measured-evaluation.md`](../handoffs/measured-evaluation.md) |
| 4 | Zero budget violations and zero hallucinated purchases for the shipped model on the test set, or true numbers | **FAIL** (no shipped model) | Only scripted-shopper pipeline numbers exist: 0 charged violations, 0 hallucinated purchases ([`summary.json`](../runs/rc-real-20261102/summary.json)); they are not model results and are labelled so |
| 5a | Public repo | **PASS** | `gh repo view Back-Nit1/crucible --json visibility` = PUBLIC (checked by `scripts.check_submission`) |
| 5b | MIT license visible in About | **PASS** | `gh repo view --json licenseInfo` key `mit`; [`LICENSE`](../../LICENSE) |
| 5c | README: infrastructure table, diagrams, our own screenshots, setup, reproducible commands, Tools Used | **PASS** | [`README.md`](../../README.md); SVGs [`docs/diagrams/`](../diagrams) (10); screenshots [`docs/screenshots/`](../screenshots) (live mode, 7 files) |
| 5d | README judge credentials | **FAIL / OWNER** | Placeholders `<<JUDGE_BUYER_EMAIL>>`, `<<JUDGE_BUYER_PASSWORD>>`, `<<LIVE_URL>>`, `<<LIVE_API_URL>>`, `<<YOUTUBE_URL>>`; only the owner publishes them |
| 6 | Commit history shows steady small commits across the period | **PASS** | 261+ commits from 2026-10-30: `git log --format=%ad --date=short \| sort \| uniq -c`. First commit is inside the period (starts 2026-10-01) |
| 7 | Postman collection for all PayPal flows and API endpoints | **PASS** | [`postman/`](../../postman); newman: 21 requests, 39 assertions, 0 failed (API folders, real data); PayPal steps 1-5 pass live, steps 6-10 need the human approval by design |
| 8 | Demo mode masks third-party brands for the video | **PASS** (text) | [`api/masking.py`](../../api/masking.py), [`tests/test_api_masking.py`](../../tests/test_api_masking.py), [`web/src/test/brand-masking.test.ts`](../../web/src/test/brand-masking.test.ts). Limit: brand names in free text without a `brand` field are not detected |
| 9 | Hosted demo stays up through 2026-12-15 | **FAIL / OWNER** | Not deployed. Free instances sleep; keep-alive monitor documented in [`docs/DEPLOYMENT.md`](../DEPLOYMENT.md) |

## Official rules (prompt.md section 2)
| Item | Result | Evidence / what is missing |
|---|---|---|
| PayPal integration central, free sandbox | **PASS** | [README "Why PayPal is central"](../../README.md#why-paypal-is-central), [`payments/`](../../payments), live check |
| Works as described; setup instructions in repo | **PASS** | README Setup; `uv run pytest -q`: 648 passed, 1 failed, 3 skipped, 6 deselected on 2026-11-12 (the failure, `test_malformed_output_is_retried_boundedly_then_fails_closed_without_keeping_raw_text`, comes from the uncommitted `raw_output` audit change in `agents/model.py`) |
| Text description | **PASS (draft)** | [`devpost.md`](devpost.md); OWNER pastes it and fills placeholders |
| Demo video under 3 min, public YouTube, English, no third-party marks or music | **FAIL / OWNER** | Not recorded. Script and recording list: [`video-script.md`](video-script.md) |
| Existing project significantly updated, explained | **PASS** | First commit 2026-10-30, in period; statement in README and Devpost |
| Free and available to judges until 2026-12-15 | **FAIL / OWNER** | Needs the deploy and keep-alive |
| Test credentials in README, no paid keys published | **PARTIAL** | Placeholders only; `scripts.secret_scan` = 0 findings with real env values; no `.env` tracked |
| Third-party data used within terms | **PASS (documented)** | Channel3 display-only/opt-in, no snapshot ([`DECISIONS.md`](../../DECISIONS.md)); Amazon Reviews 2023 frozen snapshot as a research dataset |
| Judging may use automated AI analysis: README precise and verifiable | **PASS** | Each README claim names a file or command; unmeasured items say **Not run** |

## Milestones and process (prompt.md section 16)
| Item | Result | Evidence |
|---|---|---|
| Tags `m1-day1-checks`, `m2-catalog-tasks`, `m3-episode` | **PASS** | `git tag -n1`; placement in [`DECISIONS.md`](../../DECISIONS.md) |
| Tags `m4-world`, `m5-train-eval` | **FAIL** | Not created on purpose: no trained adapter (3 real SFT smoke runs failed) and no complete evaluation exist. `check_submission` is 14/18: these two, `m8-submission`, and the placeholders |
| Tags `m6-product`, `m7-polish` | **CREATED, caveat** | Created at the submission-package commits on request. Their listed contents are not all met (no Render deploy, no Astropods, no final evals); this checklist is the honest account |
| Tag `m8-submission` | **PENDING** | Due 2026-11-12 morning (buffer) |
| `/ponytail-audit` run | **PASS** | [`ponytail-audit.md`](ponytail-audit.md) (findings listed, none applied) |
| `/graphify .` refreshed | **PASS (code only)** | [`docs/graph/GRAPH_REPORT.md`](../graph/GRAPH_REPORT.md): 3536 nodes, 11228 edges from an AST-only update; docs were not re-extracted semantically |
| `docs/ARCHITECTURE.md` updated | **PASS** | Checkout sequence rewritten, status section updated, all 10 diagrams export to SVG |
| Tests green on `main` | **PARTIAL** (green at the last commit; 1 failing test in the working tree) | see the row above; web 2026-11-12: typecheck clean, 29 vitest passed. `npm run build` and Playwright e2e **not re-run** today (last run 2026-11-03) |
| `scripts.verify_deploy` against hosted URLs | **NOT RUN** | Nothing deployed; passed 11 of 11 against a local live-mode stack |

## What only the owner can do (in order)
1. Authorize Modal spend if a model result is wanted (`CRUCIBLE_MODAL_*` gates), then run the probe, training and evaluation.
2. Deploy on Render with the runbook; run `scripts.verify_deploy`; add the keep-alive monitor.
3. Create or choose the sandbox buyer for judges; fill every `<<...>>` placeholder; re-run `scripts.check_submission`.
4. Record and upload the video (YouTube, public, under 3:00); paste the URL.
5. Paste [`devpost.md`](devpost.md) into Devpost; tag `m8-submission`.
