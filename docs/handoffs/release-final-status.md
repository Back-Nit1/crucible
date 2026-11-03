# Release-final status (Agent A, platform)

Branch `feat/release-final`. Append 3-6 lines every ~30 min.

## 2026-11-02/03 Phase 1
- Done: merged `origin/feat/paypal-live-checkout` (no conflicts); Kernel approver fixes on top of the hardened one (role-based Next/Log In, Next retry, `#one-time-cta`, scrubbed diagnostics, `Accept-Language: en-US`, bounded whole-login retry, `return_url` redirect after pay is success). API: sandbox backend builds `GuardedPayments(..., ledger=PaymentLedger("sandbox"))`, `/payments/ledger` serves it, `PaymentUnavailable` maps to 503 `payment_unavailable`, `CORS_ALLOW_ORIGINS`, `CRUCIBLE_MODEL_BACKEND=qwen` gate (uses `ModalQwenClient.from_environment()`; the brief's `QwenInferenceClient` is the protocol in `agents.model`).
- Baseline on origin/main: 350 pytest passed, 19 vitest passed; `npm run build` needs `NEXT_PUBLIC_API_BASE_URL` set (it throws without it; Render must set it). After Phase 1: 361 pytest passed.
- Live PayPal sandbox: 8 of 8 authorized runs used, 1 end-to-end pass, 5-in-a-row target NOT reached. See `docs/payments/paypal_live_check.json` and `docs/spikes/paypal-kernel.md` section 8. Open: login form resets to the email step on some runs (cause unknown).
- Ledger is in-process memory: a Render restart empties it (sandbox charges still exist in PayPal).
- Blockers: no more authorized live runs; Modal gates absent from `.env` (not needed for Phase 1).

## 2026-11-03 Phase 2 (deploy readiness)
- Done: `render.yaml` (api: `PAYMENTS_BACKEND=sandbox`, `DEMO_MODE=1`, `REQUIRE_ALL_IN_QUOTE=0`, secrets `sync: false`, new `CORS_ALLOW_ORIGINS`, `PAYPAL_RETURN_URL/CANCEL_URL`, `CRUCIBLE_MODEL_BACKEND`, `MODAL_TOKEN_*`; web: `rootDir: web`, `NEXT_PUBLIC_DATA_MODE=live`); `scripts/verify_deploy.py` (11 checks, tested with fake hosts and run for real against a local live-mode web + API on the real Elastic index: 11/11 passed); DEMO_MODE brand masking (`api/masking.py`) with tests; samples regenerated; vitest 22 passed; `npm run test:e2e` 6 passed, 2 skipped (viewport-specific); Agent B's `READY-TO-MERGE ded4e44` merged (542 pytest passed, 1 skipped).
- `render` CLI is not installed: **nothing was deployed**. Click-by-click runbook is in `docs/DEPLOYMENT.md`.
- Masking limits: text only (no images/logos exist in code; a web test enforces that). Brand names that appear only in free text with no `brand` field (task text, review text of other brands) are not detected.
- Not done: dark-mode/a11y re-audit beyond the existing e2e (keyboard nav on mobile passes); no Lighthouse/axe run by me.
- User TODO: do the Render runbook; set a free uptime monitor; decide on Kernel approval for the video (flaky, see spike doc section 8).
