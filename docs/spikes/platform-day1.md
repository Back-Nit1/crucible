# Platform Day-1 findings (agent 1)

Date 2026-10-31. Branch `feat/platform-m1-m3`. Builds on the earlier spikes ([catalog-elastic](catalog-elastic.md),
[paypal-kernel](paypal-kernel.md), [modal-qwen](modal-qwen.md)); this file records what was **re-verified live** here and what is still blocked.
No tokens, approval URLs, cookies or credentials appear anywhere in this report.

## Scorecard

| Check | Result |
|---|---|
| Secrets in tracked files / git history | **PASS**: every non-blank `.env` value searched across `git log --all -p` and HEAD: 0 hits; token-shape regex: 0 hits. `.env` ignored; `.env.example` blank. Earlier note: 4 dangling blobs in the original checkout's object store held real values (not in any ref); rotate KERNEL, Modal, Elastic, Zapier credentials if not already. |
| Modal token rotated | **UNVERIFIED**: the token in `.env` authenticates (`modal token info` exit 0) but nothing proves it is the *replacement*. User must confirm. |
| PayPal OAuth | **PASS** live: 200, 392-607 ms (3 calls). |
| PayPal create / get / idempotent replay | **PASS** live (`tests/test_payments_live.py`): same `PayPal-Request-Id` returns the same order; status `PAYER_ACTION_REQUIRED`. Earlier 5-order sample: create median 670 ms, get 371 ms. |
| PayPal capture | **Bug found and fixed**: body-less `POST /capture` returns `UNSUPPORTED_MEDIA_TYPE`; fixed by sending `{}`. Capture before approval now live-verified to raise `OrderNotApproved`. |
| PayPal approve, capture success, duplicate capture, capture latency | **BLOCKED**: no sandbox buyer account (`PAYPAL_SANDBOX_BUYER_EMAIL/PASSWORD` unset). |
| Kernel approval | **BLOCKED** on the same buyer credentials. Credential-free probe (earlier spike) found the login page loads with a reCAPTCHA frame present; whether login is challenged is unknown. No CAPTCHA/stealth/proxy features are used. |
| PayPal Agent Toolkit | **Not adopted**: no confirmed approval link/idempotency/order-by-id (see paypal-kernel spike). |
| Channel3 | **Live probe run**: 16 calls, 12 credits (cap 25 calls / 20 credits). See below. |
| Amazon Reviews 2023 | Coverage table from earlier spike stands (lower bounds); streaming snapshot builder added. |
| Elastic Serverless | **PASS** live: connect, mappings, keyword / vector / hybrid, product-scoped retrieval. |
| Elastic from Modal / Render | **NOT RUN** (needs a Modal secret; Render not built). |
| Modal auth + Volume resume | **PASS**: fresh run, stopped after committed step 3, resumed at 3, finished 4-6 (`results/day1_modal_resume.json`). |
| Modal GPU / Qwen 20-prompt probe | **BLOCKED**: `Please add a payment method to use L4 GPU functions.` Spend $0. Ceiling for the probe is $0.862 (L4, 45 min). No tool-call numbers are claimed. |
| Astropods / skills | Unchanged from DECISIONS.md: Astropods blocked on `ast login`; APIMatic plugin not installed (interactive). |
| Best Buy | Disabled; not evaluated, not bypassed. |

## Channel3 (live, 16 calls / 12 credits)

Per category, top 20 search results (`/v1/search`, 1 credit each) for a representative query, plus 4 free product-detail calls:

| Category | offers | in-stock offer | has variants | size option | ratings rollup | median rating count | structured attrs |
|---|---|---|---|---|---|---|---|
| running shoes | 100% | 100% | 30% | 25% | 75% | 85 | 100% |
| hiking/outdoor | 100% | 100% | 35% | 25% | 35% | 185 | 100% |
| headphones | 100% | 100% | 5% | 0% | 50% | 3 | 100% |
| water bottles | 100% | 100% | 5% | 5% | 30% | 760 | 100% |
| desks/office | 100% | 100% | 40% | 10% | 50% | 53 | 95% |
| video games | 100% | 100% | 0% | 0% | 25% | 113 | 100% |
| PC components | 100% | 100% | 0% | 0% | 35% | 5 | 100% |
| textbooks | 100% | 100% | 0% | 0% | 0% | 0 | 100% |
| clothing | 100% | 100% | 25% | 20% | 45% | 31 | 100% |
| furniture | 100% | 100% | 30% | 0% | 60% | 6.5 | 100% |
| dev tools | 100% | 100% | 25% | 0% | 25% | 5 | 100% |

- **Reviews: none.** No key containing "review" appears in any response; only a ratings rollup. `get_reviews` therefore returns nothing (`reviews: none`).
- **Variant availability** (`available`) is **never** populated in search results (0 of all size values) but **is** populated on product detail (e.g. 17/17, 15/15 size values on 3 of 4 sampled details). A size-constrained live purchase needs a detail call first.
- **Price filter is not trustworthy**: results contained offers above `max_price` (running shoes 6/20, furniture 4/20 products had an offer over the cap). The router re-filters by the selected offer price; payment guards re-check the live price.
- The attribute filter (`footwear-support-type=Neutral`, `category=athletic-shoes`) returned 20 results, so attribute filtering works.
- Terms (from the earlier doc review, to be confirmed by a human against the ToS text): training on output and bulk storage are prohibited; publishing benchmark results needs consent. Channel3 can be a **live display source only**, not a snapshot, training source or review source.

## Elastic Serverless (live)

- Serverless; direct project endpoint is derived from the Cloud ID by `endpoint_from_cloud_id` (works). Auth `ApiKey`.
- `.multilingual-e5-small-elasticsearch` **times out (HTTP 408, model deployment start >30 s)** on this project, twice. Switched to the EIS-hosted `.jina-embeddings-v5-text-nano`: **768 dims, ~0.17 s**, max 16 inputs per request. `DIMS`/`EMBED_ID` updated; bulk is chunked, retried and refreshed once.
- Spike run on 8 Video_Games products / 8,720 real reviews in disposable `spike_*` indices (dropped afterwards): keyword, vector and hybrid (RRF with product filter) all returned only reviews of the requested product. Hybrid for "stopped working after a few weeks" returned five genuine failure reviews; keyword alone missed phrasing variants, vector alone returned one off-topic review. For "battery life" (a concern the game does not have) all three modes returned irrelevant reviews: **retrieval does not know when nothing relevant exists**, so the agent layer must not treat a returned review as evidence of the concern.
- Real review text contains HTML (`<br />`, entities) and at least one affiliate-spam link: the UI must escape/strip review text.
- Mappings: `catalog/providers/elastic.py::mappings()` (products, reviews, traces incl. `task_text` + `embedding`, kill_rules, generations).
- Reproduce: `uv run python -m scripts.day1_live --env-file .env elastic --category Video_Games --products 8 --drop`.

## Decisions taken

See `config/providers.yaml` and DECISIONS.md: training/eval = Elastic snapshot always; live chat default = Elastic snapshot (Channel3 is opt-in because it has no review text, so it cannot produce review-grounded picks); Best Buy disabled.
