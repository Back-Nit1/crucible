# Day-1 spike: catalog provider, Elastic hybrid search, review coverage

Branch `feat/catalog-elastic-day1`. Spec checks 4 (catalog provider), 7 (Elastic hybrid), 8 (review coverage).
Recommendation only; the integration owner decides. Date: 2026-10-31.

## Status

| Item | Status |
|---|---|
| Channel3 docs, pricing, terms review | done (documentation only) |
| Channel3 live auth + measured responses | **NOT RUN**: key was not in the process environment and credential-file access was not permitted in this session. 0 credits used. |
| Elastic live connect / mappings / hybrid demo | **NOT RUN**: same reason. 0 Elastic calls. |
| Mappings, hybrid query, providers | written + unit-tested offline (fake transport) |
| Amazon Reviews 2023 bounded sample, join, coverage | done, measured |
| Shoe attribute probe rerun | done, measured |
| Best Buy | disabled (signup rejected). Not evaluated, not bypassed. |

Run the two live probes with `--env-file` pointing at a file that holds `CHANNEL3_API_KEY`,
`ELASTIC_API_KEY` and `ELASTIC_ENDPOINT` (Serverless project endpoint URL; the Cloud ID in `.env.example`
is only a best-effort fallback):

```
uv run python -m scripts.day1_live --env-file <file> channel3 --max-credits 20   # <= 20 credits, product detail is free
uv run python -m scripts.day1_live --env-file <file> elastic --category Video_Games --drop
```

The Channel3 probe stops at the credit cap, records per-category offer/stock/variant/ratings/attribute
coverage, scans every response for any `review` key, and checks whether the attribute filter works. Raw
responses go to `data/raw/` (gitignored) and are never committed.

## Channel3 (documentation findings)

Sources: channel3.ai/docs (pricing, search and product-detail API reference, caching guide, rate limits) and
the Channel3 Terms of Service. The terms page was read through a summarising fetch; a human should confirm
the quoted clauses verbatim before relying on them.

- Auth: `x-api-key` header. Search is `POST https://api.trychannel3.com/v1/search`.
- Cost: `/search` 1 credit; `GET /v1/products/{id}` free; 1000 free credits/month; overage $0.007/credit.
  This is the documented cost; the measured cost depends on the live run (compare dashboard usage before/after).
- Filters: brand, gender, age, price min/max, availability, sale, website, category, exclusions, colors (beta),
  `attributes` (per-category keys, e.g. digital cameras: `camera-sensor-type`), dimensions.
- Variants: `variants.options[].values[]` with `exists`, and `available` (InStock/OutOfStock) populated **only on
  product-detail, not search**. Offers carry InStock/OutOfStock and price. No unit stock counts.
- Reviews: **no review text.** Only a `ratings` rollup (`value`, `count`, `source_count`). Docs describe no review endpoint.
- Rate limits: new keys on `default` plan, 10 req/s, 10,000/day.

### Terms (blockers for snapshot / training)

| Question | Finding |
|---|---|
| Training / fine-tuning on output | **Prohibited**: ToS s.7 bars using Customer Output or Channel3 IP "to train, fine-tune, or otherwise improve a machine-learning or language model", including synthetic training data for that purpose. |
| Snapshot / storage | **Prohibited at scale**: s.7 bars caching/storing/redistributing "a significant portion of the Channel3 product catalog or Customer Output". Caching guide: IDs may be cached indefinitely; prices/availability/offer URLs must be refreshed, TTL of minutes to hours. |
| Publishing eval results | s.7 bars publishing benchmark/evaluation results of the Services without written consent (affects any Channel3-based accuracy claim). |
| Live display | Allowed with short-lived caching; commission disclosure required where affiliate links are shown. |

**Result:** a Channel3 snapshot for training/eval is a no-go. Live chat use only.

## Amazon Reviews 2023 (measured)

Method (`scripts/day1_coverage.py`, deterministic, reproducible): for each dataset category, 4 evenly spaced
byte windows of 25 MB of metadata and 4 of 50 MB of reviews; join by `parent_asin`. Use-case segments are
keyword matches on the category path + title. Raw windows cached under `data/raw/`; results in `coverage.json`.

Findings about the data that shape the pipeline:
- Review files are ordered by user, not product, and metadata is unordered, so a bounded window only holds a
  thin slice of each product's reviews. Numbers below are **lower bounds** (a product's real review count is
  `rating_number`; we only count reviews actually held).
- The dataset has **no review ID**. Review IDs are composed from original fields only:
  `parent_asin:asin:user_id:timestamp`. Flag for the integration owner.
- No size, stock or variant data exists. Sizes live in free-text `details` for 33/1706 sampled running-shoe
  listings (1.9%), as a single value (e.g. "10 D(M) US"), not per-size stock. `Item Package Quantity` is pack count.

### Coverage table (sample; "usable" = real price and >= 5 real reviews held in the sample)

| Segment (dataset category) | Products in sample | With price | Reviews joined | >= 5 reviews held | Usable |
|---|---|---|---|---|---|
| Running shoes (Clothing_Shoes_and_Jewelry) | 1,706 | 284 | 743 | 48 | 36 |
| Clothing items (Clothing_Shoes_and_Jewelry) | 10,468 | 3,113 | 8,803 | 243 | 231 |
| Hiking/outdoor (Sports_and_Outdoors) | 3,874 | 1,090 | 2,592 | 115 | 97 |
| Water bottles (Sports_and_Outdoors) | 1,088 | 293 | 1,318 | 53 | 38 |
| Headphones (Electronics) | 2,376 | 700 | 922 | 41 | 31 |
| PC components (Electronics) | 2,433 | 1,095 | 713 | 29 | 16 |
| Video games (Video_Games, all) | 31,651 | 15,000 | 102,792 | 3,471 | 2,445 |
| Desks/office (Office_Products) | 4,871 | 1,857 | 5,175 | 195 | 152 |
| Textbooks/study (Books) | 1,199 | 1,137 | 46 | 0 | 0 |
| Furniture (Home_and_Kitchen) | 2,387 | 806 | 526 | 27 | 25 |

Whole-category rows are in `coverage.json`. Only 17-95% of sampled products carry a price (shoes 17%, books 95%) (prices were not
back-filled; unpriced products are excluded).

### Shoe attribute probe (rerun)

The earlier probe over-counted: its key regex matched `Date First Available` and `Item Weight`. Rerun on 1,706
running-shoe listings with exact key buckets: size 33, width 1, weight 93, stock/inventory 0 (13 matches were
`Item Package Quantity`), features present on 1,510. **Size, width and stock are not checkable for shoes.**

## Elastic (offline-verified only)

From the Elastic docs: Serverless connects by project endpoint URL + `Authorization: ApiKey`; no shard/replica
settings; the `rrf` retriever takes a top-level `filter` applied to every child retriever; the knn retriever
takes `field`, `query_vector`, `k`, `num_candidates`, `filter`; embeddings via
`POST /_inference/text_embedding/{id}` (default `.multilingual-e5-small-elasticsearch`; availability on this
project is unverified until the live run).

Implemented and unit-tested (fake transport): mappings for `products`, `reviews`, `traces`, `kill_rules`,
`generations` (`catalog/providers/elastic.py`); `hybrid_review_query` = RRF(keyword multi_match, knn) with the
`product_id` term filter; `ElasticCatalogProvider` (search/get_product/get_reviews, preserving `source`,
`as_of`, original review id and `product_id`); idempotent bulk indexing. **Not yet shown against a real
cluster:** that the mappings are accepted, that the inference endpoint exists and its dimension is 384, and
that hybrid results stay scoped to one product. The `elastic` probe prints keyword-only, vector-only and hybrid
results per focus query and a scope check for that purpose. Hybrid search "from Modal and Render" is untested.

## Review-trap eligibility (recommendation)

Review traps need many reviews per product and persona-relevant content (fit, weight, durability, comfort).
Based on the lower-bound counts above:

- Eligible: running shoes / clothing (fit and weight talk), hiking/outdoor, headphones (comfort/fit), desks/office, furniture (thin, soft).
- Volume-rich but persona-weak: video games (use for non-trap tasks and general review grounding).
- Marginal: water bottles, PC components (small usable counts; specs dominate over persona).
- Exclude: textbooks/study (no products with 5 held reviews).
- Shoes/clothing tasks must not use size or stock constraints (not verifiable). Do not synthesise them.
- Before M2, index from larger or product-targeted windows and keep only products with >= 5 reviews actually held.

## Recommended provider chain (for the integration owner)

1. Training/eval: Amazon Reviews 2023 frozen snapshot in Elastic (as per spec 6.2). Channel3 snapshot rejected on terms.
2. Live chat: Channel3 only if the live run confirms coverage, and only for displaying products (no review text; no persisting beyond short TTL; show ratings rollup as such). Best Buy disabled. Otherwise `ElasticCatalogProvider` labelled "snapshot data".
3. Channel3 go/no-go: **no-go for snapshot/training; conditional go for live product display** pending the live measurement.
