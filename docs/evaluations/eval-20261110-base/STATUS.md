# eval-20261110-base: PARTIAL, 86 of 141 records, 0 successes. NOT A RESULT

The base-model evaluation was started and stopped early. There is no `report.json` and nothing was published, on purpose: a partial run
is not a measurement of the base model, and it says nothing about a fine-tuned one (none exists).

| | |
|---|---|
| manifest | `manifest.json` (hash `a3deb0bb8c70b121f16409242c67a2c1b8620109a574d2cd3ff7ac4ce3d2eed6`) |
| matrix | 47 protected tasks x 3 seeds (20261201-03) = 141 (task, seed) pairs per contender |
| contender run | `base-qwen` only (`base-qwen-memory` needs a non-empty audited pool of real model traces: none exist; `survivor-finetuned` needs a real adapter: none exists) |
| records on disk (2026-11-12) | **86 of 141** in `checkpoints/evaluations/eval-20261110-base/episodes/` (git-ignored, resumable), plus 12 quarantined infrastructure failures |
| outcomes | 53 `malformed_action`, 27 `model_failure`, 6 `instant_kill`, **0 successes** |
| prompts / harness | prompts v5; the base agent fails structurally (calls `get_reviews` / `propose_purchase` before open/compare, which the state machine rejects; 6 tasks have budgets below every product price; some episodes pass the 8192-token input limit). Pilot `pilot-v6-state-tools` tested a tool-order fix and was interrupted at 12/141 |
| payments | mock |
| WebShop | `blocked_not_run` (`webshop_base-qwen_blocked_not_run.json` lists the unmet requirements) |
| spend | about $2.70 billed on Modal of the $3.00 approved ceiling; the inference app is stopped (verified 2026-11-12: no `crucible-qwen-inference` app) |

Finishing the other 55 records needs about $0.5-0.7 more, above the ceiling, so it waits on the owner raising
`CRUCIBLE_MODAL_APPROVED_CEILING_USD`. Harness fixes should come first (see DECISIONS.md 2026-11-12).
Commands: "Commands" in `docs/handoffs/measured-evaluation.md`.
