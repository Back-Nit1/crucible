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

## 2026-10-30 Day-1 check 4b/8 (partial): Amazon Reviews 2023 coverage
Method: first 40 MB of each `meta_<Category>.jsonl` (prefix sample, may be biased by file order).
"usable" = numeric price AND `rating_number` >= 5. Review text not fetched yet.

| Category | products | price | >=5 reviews | usable |
|---|---|---|---|---|
| Video_Games | 11315 | 5989 | 9511 | 5467 |
| Sports_and_Outdoors | 13728 | 6610 | 10782 | 5896 |
| Electronics | 10869 | 4683 | 8449 | 4008 |
| Office_Products | 11723 | 6103 | 9165 | 5332 |
| Home_and_Kitchen | 10800 | 5627 | 8674 | 5005 |
| Clothing_Shoes_and_Jewelry | 13988 | 7602 | 11967 | 7202 |
| Software | 14196 | 2718 | 8455 | 1466 |
| Musical_Instruments | 12112 | 6126 | 8913 | 5174 |
| Books | 10725 | 9705 | 8453 | 7655 |

Findings:
- ~40-50% of products have price + enough reviews (Software is weak on price: drop from tasks).
- **No stock or per-size availability in the meta schema** (fields: title, price, features,
  description, details, categories, store, average_rating, rating_number, parent_asin...).
  `details['Size']` appeared on ~248 of ~14k Clothing prefix records. Spec's "size 12 in stock"
  hard constraint therefore cannot come from this dataset. Needs a decision: drop size/stock
  constraints for training tasks, or synthesize a deterministic stock/size snapshot (must be
  disclosed; never presented as real Amazon stock). Not decided; blocks task generator.
- Review files are 1.5-31 GB per category (`review_categories/<Cat>.jsonl`), joined on
  `parent_asin`. Full-file streaming filter needed per category; Video_Games 2.7 GB and
  Musical_Instruments 1.6 GB are the cheapest. Not downloaded yet.
- Caveat: my first shoe-attribute probe filtered on a substring that matched every record, so
  its attribute counts are unreliable; rerun with a proper category filter.
- License: dataset page states none; cite Hou et al. 2024 (arXiv:2403.03952), research use.
