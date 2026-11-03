# Ponytail audit (repo-wide, 2026-11-03)

Scope: over-engineering only. Findings are listed, none applied (a cleanup this close to submission would only add risk). Scan method: file sizes, `Protocol` classes and their implementations, `scripts/`, declared dependencies against imports (`pyproject.toml`, `web/package.json`).

1. `delete:` four one-off PayPal/Kernel spike scripts (`scripts/paypal_kernel_e2e.py` 58, `paypal_latency.py` 49, `paypal_oauth_check.py` 18, `kernel_probe.py` 32 lines) now covered by `scripts/paypal_live_check.py`, which has latency per step, a ledger and typed exit codes. Keep only if the spike docs still cite them. [scripts/]
2. `shrink:` `scripts/export_api_samples.py` (44, needs Elastic) and `scripts/export_buyer_samples.py` (63, offline) are two sample exporters with overlapping jobs. One script with a `--live` flag. [scripts/]
3. `shrink:` `api/main.py` builds `GuardedPayments` twice (`get_payments` and `default_buyer`) with the same arguments. Build once in `get_payments` and pass it to the buyer. [api/main.py]
4. `yagni:` `Protocol` classes `MutationProposer`, `TrainBackend`/`CheckpointBackend`, `Engine`, `QuoteProvider` are duck-typed with one real implementation plus a test double each. Acceptable as test seams; delete any whose only second implementation is a fake. [world/evolution.py, training/, modal_app/qwen_service.py, payments/quote.py]

Checked and fine: no unused Python dependency (`jsonschema`, `pyyaml` each have a user); no unused web dependency (`react-dom` is required by Next/React); no wrapper-only modules found in `api/`, `payments/`, `catalog/`.

net: -~160 lines, -0 deps possible.
