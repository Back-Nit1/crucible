# Crucible: Devpost text

Plain statement of what exists. Every number links to the file it comes from. Placeholders in `<<...>>` are filled by the owner at submission.

**Tagline.** An evolutionary RL world that trains an open model to shop on PayPal, and a checkout that never charges without an explicit confirmation.

## What it does
Crucible has two halves.

**The world.** A population of shopping-agent genomes plays seeded tasks (feasible, impossible, review-sensitive) over a frozen product and review snapshot in Elastic. Every episode runs through one state machine with typed tools and a guarded payment layer, and is scored with `fitness = G x Q - efficiency`. Eight versioned kill rules end an episode the moment an agent hallucinates a product, refuses a feasible task, exceeds the budget, skips research, double-pays, fabricates review evidence, skips reviews or games the review signal. A Loophole Hunter proposes new rules (it never enables them). Survivors' grounded traces are curated into a hashed SFT manifest for a LoRA run on an open Qwen model.

**The product.** A shopping chat (Next.js) turns a raw request into parsed intent and assumptions, a research timeline, product cards with source and date, review evidence cited by review id, and a verified quote. Nothing is charged until the buyer confirms. Checkout is PayPal sandbox Orders v2: create order, buyer approves on PayPal's page, capture, receipt. AG Grid dashboards expose episodes (server-side sort and filter, replay, CSV) and the payment ledger.

## Why PayPal is central
Every purchase in the world, the API and the chat goes through [`payments/`](../../payments). `SandboxPayments` creates the order with a stable `PayPal-Request-Id` (a retry cannot create a second order or charge), the buyer approves, and `confirm_and_pay` captures only with `user_confirmed: true`, a fresh quote and an in-budget total. Live result on 2026-11-02 (sandbox, $1.00 USD): create, idempotent replay, capture-before-approval rejected, buyer approval, capture `COMPLETED`, replay returned the same capture id, one capture on the order ([`docs/payments/paypal_live_check.json`](../payments/paypal_live_check.json)).

## How we built it
Python 3.12 / FastAPI service and a Next.js 16 app; Elastic Serverless for products, embedded reviews (hybrid search), traces, generations and kill rules; PayPal sandbox via the Orders v2 REST API; Kernel cloud browsers for automated buyer approval in checks; Modal for resumable CPU world runs; a Postman collection with tests in every request; AG Grid Community for the episode explorer and the ledger; Render blueprint for hosting. Architecture and sequence diagrams: [`docs/ARCHITECTURE.md`](../ARCHITECTURE.md). Build log: 261 commits from 2026-10-30, milestone tags `m1`..`m3` (and later tags) in `git tag`.

## What we measured (and what we did not)
- Real-snapshot generation `rc-real-20261102`: 96 episodes, 40 completed purchases (mock payments), 0 hallucinated purchases, 0 budget violations charged (5 attempts blocked at the guard), 21 of 24 correct no-matches, review grounding 91 of 91, 3 of 8 genomes survived, 30 curated SFT records ([`summary.md`](../runs/rc-real-20261102/summary.md)). Shoppers were **scripted** and read the reference answer, so this proves the pipeline, not model quality.
- **Not run:** Qwen tool-call probe ([probe](../model-runs/qwen-probe-20261101/probe.md)), LoRA training ([dry run plan only](../model-runs/dryrun/STATUS.md)), base vs memory vs fine-tuned evaluation ([status](../evaluations/eval-20261110-base/STATUS.md)), WebShop. GPU spend: $0.

## Challenges
- **The PayPal approval page changes under automation.** The Kernel approver failed three of its first runs because the sandbox login rendered in Portuguese, then because a form reset to the email step. After fixes it completed 1 of 8 authorized runs; we report that number and have judges approve by hand ([`paypal-kernel.md`](../spikes/paypal-kernel.md) section 8).
- **Cheating is cheap, so rules are cheap to test.** Planted fixture genomes (hallucinator, budget-buster, wrong-refuser, review-limit-one) prove each kill rule fires.
- **Split leakage.** Whole-category feasible sets let test tasks share products with train tasks; the evaluation set was rebuilt product-disjoint and audited ([`audit.json`](../evaluations/taskset-20261110/audit.json)).
- **No stock or size in the dataset.** Amazon Reviews 2023 has none, so those constraints are never generated; stock, size, shipping and tax are `unknown`, not zero ([`DECISIONS.md`](../../DECISIONS.md)).
- A live-mode browser bug (`Illegal invocation` from an unbound `fetch`) only appeared when we took live screenshots; fixed and tested ([`client.test.ts`](../../web/src/lib/api/client.test.ts)).

## Accomplishments
A reproducible, resumable generation (interrupted at 40 episodes, resumed to 96, rerun reproduces the summary byte for byte per [`release-convergence.md`](../handoffs/release-convergence.md)); a payment layer that cannot capture without confirmation, a fresh quote and an in-budget total ([tests](../../tests/test_api_sandbox.py)); typed, honest UI states (**Not run**, **Not measured**, **unknown**); 548 Python tests, 23 web unit tests, Playwright e2e, a Postman collection that passes against the real API.

## What we learned
Honest evaluation needs the denominator next to every number, planted failures to prove guards, and a hard separation between privileged scripted shoppers and any model.

## What's next
Enable the Qwen endpoint on Modal (needs the owner's billing approval), run the bounded probe, train the LoRA on real-model survivor traces, run the base vs memory vs fine-tuned evaluation on the audited held-out set, and publish whatever it shows, good or bad. Deploy to Render ([runbook](../DEPLOYMENT.md)). Not built: Astropods, Zapier.

## Built with
PayPal sandbox (Orders v2), Elastic Serverless, Kernel, Modal, Render, AG Grid Community, Postman, Next.js, React, Tailwind CSS, TypeScript, Zod, FastAPI, Pydantic, Python, uv, Qwen (target model, not yet run), Amazon Reviews 2023 (McAuley Lab), Mermaid, Playwright, Vitest, Channel3 (opt-in, display only).

## Significantly updated during the submission period
The repository's first commit is 2026-10-30, inside the submission period (from 2026-10-01); all code was written in the period and history is unmodified (`git log`). Details: [README](../../README.md#how-this-was-significantly-updated-during-the-submission-period).

## Testing instructions
Hosted demo `https://crucible-2rcx.onrender.com`, API `https://crucible-api-t6pn.onrender.com`, sandbox buyer `<<JUDGE_BUYER_EMAIL>>` / `<<JUDGE_BUYER_PASSWORD>>`, video `<<YOUTUBE_URL>>`, repo https://github.com/Back-Nit1/crucible (MIT). Step by step, including a path that works without a model: README section "Judge testing". Free to use through the judging period; sandbox only, no real money.
