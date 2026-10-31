# Platform status (agent 1) — branch `feat/platform-m1-m3`

Updated after phases 0-4. Latest commit: see `git log -1`. Tests: `uv run pytest -q` -> all pass, 2 live tests deselected (`-m live`).

## Contracts agent 2 can consume (no Elastic import needed)
| Contract | Module | Notes |
|---|---|---|
| `Product`, `Review`, `CatalogProvider` | `catalog.providers.base` | Money is `Decimal`. `variants` is empty for Amazon data (no stock/size exists): never assume size/stock constraints are checkable. |
| `ProviderRouter(providers, config).search/get_product/get_reviews(mode="live"\|"training"\|"eval")` | `catalog.router` | Results carry `provider`, `source`, `as_of`, `snapshot`, `fallback_from`; reviews carry `reviews_available`. training/eval are pinned to the Elastic snapshot. |
| `ElasticCatalogProvider` | `catalog.providers.elastic` | Build with `Elastic(url)`; env `ELASTIC_ENDPOINT` or `ELASTIC_CLOUD_ID`, `ELASTIC_API_KEY`. |
| `PaymentsBackend`, `MockPayments(auto_approve)`, `SandboxPayments`, `GuardedPayments` | `payments.*` | `GuardedPayments.propose_purchase(task_id, agent_id, product_id, variant, expected_total, budget_cap)` then `confirm_and_pay(pending_id, user_confirmed)`. Guard violations (`BudgetViolation`, `PriceMismatch`, `OutOfStock`, `NotConfirmed`) are kill offenses. `MockPayments(auto_approve=True)` for bulk training. |
| `TraceRecord`, `TraceRepository.add/similar`, `InMemoryTraceRepository`, `ElasticTraceRepository` | `memory`, `memory.elastic` | `similar()` only returns `killed=false`, `fitness>=min_fitness`, `split!="test"`. Requires agent 2 to set `split` truthfully on every trace. `TraceRecord.episode` is free-form JSON. Agent 2's own trace model is not imported here; map it to `TraceRecord` at the boundary. |
| HTTP API | `api.main.create_app(router, backend)` | `/health`, `/providers/status`, `/catalog/search`, `/catalog/products/{id}`, `/catalog/products/{id}/reviews`, `/purchase/propose`, `/purchase/confirm`. Errors: `{"error": {"code", "message"}}`. |
| Snapshot data | Elastic `products` / `reviews` (no prefix) | Sports_and_Outdoors, Electronics, Office_Products, Clothing_Shoes_and_Jewelry: **590 products, 14,524 reviews live** (14,541 built; 17 id collisions). Manifest + hash per category in `data/manifests/`. Rule: top-150 by rating_number, first 1.5 GB of reviews, >=5 reviews held, <=25 kept. |

## Requested from agent 2 (documented only; nothing edited in their dirs)
- Task generation must source products from `ProviderRouter(mode="training")`; feasible sets can use price and category only. **Drop size/stock hard constraints** (not in the data).
- Review-trap eligibility: running shoes/clothing, hiking, headphones, office are plausible; textbooks have no reviews; video games are persona-weak (see `docs/spikes/catalog-elastic.md`).
- Reviews can contain HTML and spam; do not treat a retrieved review as evidence of a concern unless the text says so (retrieval returns top-k even when nothing is relevant).
- Review ids are not guaranteed unique (17 of 14,541 collided across the four snapshots).

## Environment names
`PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_ENV=sandbox`, `PAYPAL_SANDBOX_BUYER_EMAIL`, `PAYPAL_SANDBOX_BUYER_PASSWORD`, `KERNEL_API_KEY`,
`MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET`, `ELASTIC_CLOUD_ID` / `ELASTIC_ENDPOINT`, `ELASTIC_API_KEY`, `CHANNEL3_API_KEY`, `BESTBUY_API_KEY` (disabled), `ZAPIER_WEBHOOK_URL`, `PAYMENTS_BACKEND` (`sandbox` to go live-sandbox in the API).

## Blockers needing the user
1. **Sandbox buyer account** (`PAYPAL_SANDBOX_BUYER_EMAIL/PASSWORD` in `.env`): blocks Kernel approval, approve->capture, duplicate-capture and capture/approval latency checks.
2. **Modal payment method**: blocks all GPU functions (Qwen 20-prompt probe, LoRA cost estimate). Probe ceiling $0.862.
3. Confirm the `.env` Modal token is the rotated one (it authenticates; rotation unprovable from here).
4. Decide `live_chat`: Elastic snapshot (default) vs Channel3 (no reviews).
5. APIMatic plugin install and `ast login` are interactive.

## External calls and approximate cost
Channel3: 16 calls / 12 credits (free tier). PayPal sandbox: ~6 OAuth calls, ~6 orders created, 0 captures. Elastic: spike (8.7k reviews) + 4 category snapshots, embeddings via EIS. Modal: 1 CPU resume run, 1 rejected GPU launch; GPU spend $0. Hugging Face: ~1.7 GB streamed per snapshot category.

## Decisions awaiting integration
See DECISIONS.md "platform owner" section; `config/providers.yaml` is the router's source of truth.
