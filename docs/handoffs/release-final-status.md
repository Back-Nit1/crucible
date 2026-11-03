# Release-final status (Agent A, platform)

Branch `feat/release-final`. Append 3-6 lines every ~30 min.

## 2026-11-02/03 Phase 1
- Done: merged `origin/feat/paypal-live-checkout` (no conflicts); Kernel approver fixes on top of the hardened one (role-based Next/Log In, Next retry, `#one-time-cta`, scrubbed diagnostics, `Accept-Language: en-US`, bounded whole-login retry, `return_url` redirect after pay is success). API: sandbox backend builds `GuardedPayments(..., ledger=PaymentLedger("sandbox"))`, `/payments/ledger` serves it, `PaymentUnavailable` maps to 503 `payment_unavailable`, `CORS_ALLOW_ORIGINS`, `CRUCIBLE_MODEL_BACKEND=qwen` gate (uses `ModalQwenClient.from_environment()`; the brief's `QwenInferenceClient` is the protocol in `agents.model`).
- Baseline on origin/main: 350 pytest passed, 19 vitest passed; `npm run build` needs `NEXT_PUBLIC_API_BASE_URL` set (it throws without it; Render must set it). After Phase 1: 361 pytest passed.
- Live PayPal sandbox: 8 of 8 authorized runs used, 1 end-to-end pass, 5-in-a-row target NOT reached. See `docs/payments/paypal_live_check.json` and `docs/spikes/paypal-kernel.md` section 8. Open: login form resets to the email step on some runs (cause unknown).
- Ledger is in-process memory: a Render restart empties it (sandbox charges still exist in PayPal).
- Blockers: no more authorized live runs; Modal gates absent from `.env` (not needed for Phase 1).
