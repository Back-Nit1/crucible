# eval-20261110-base — PLANNED, NOT RUN

No model episode exists for this evaluation. There is no `report.json` and nothing was published, on purpose.

| | |
|---|---|
| manifest | `manifest.json` (hash `a3deb0bb8c70b121f16409242c67a2c1b8620109a574d2cd3ff7ac4ce3d2eed6`, status `planned`) |
| matrix | 47 protected tasks × 3 seeds (20261201–03) = 141 (task, seed) pairs per contender |
| contenders planned | `base-qwen` only (`base-qwen-memory` needs a non-empty audited memory pool of real model traces: none exist; `survivor-finetuned` needs a real adapter reference: none exists) |
| payments | mock |
| WebShop | `blocked_not_run` — `webshop_base-qwen_blocked_not_run.json` lists the unmet requirements and setup commands |

Blocker: `CRUCIBLE_MODAL_TOKEN_ROTATED`, `CRUCIBLE_MODAL_BILLING_CONFIRMED`, `CRUCIBLE_MODAL_APPROVED_CEILING_USD` are not set, so
`scripts.run_evaluation run` exits 3 before any model call. Spend so far: $0.

To produce the real result: see "Commands" in `docs/handoffs/measured-evaluation.md`.
