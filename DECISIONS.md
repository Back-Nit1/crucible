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

## 2026-10-31 integration owner: security, skills, Astropods (Day-1 checks 9, 10)

### Secret hygiene
- `.env` exists and is ignored (`.gitignore:1`). `.env.example` restored to its committed blank state plus blank `PAYPAL_SANDBOX_BUYER_EMAIL=` / `PAYPAL_SANDBOX_BUYER_PASSWORD=`. The real `.env` has no buyer keys yet.
- Scan (values from `.env` matched against all tracked files, `git log --all -p`, and token-shaped patterns): **0 hits**. No `.env` file was ever committed; no remote is configured, so nothing was pushed.
- Finding: 4 **unreachable (dangling) blobs** in the local object store contain real values from the modified `.env.example` (KERNEL, Modal, Elastic, Zapier keys). They are not in any commit or ref and never left this machine. Not pruned yet (needs user approval: `git gc --prune=now`). Rotate Modal (in progress); consider rotating KERNEL, Elastic, Zapier too.
- Modal is not used until authentication with the replacement token succeeds.

### Skills (check 10)
| Item | Status | Evidence |
|---|---|---|
| Ponytail | OK | skill `ponytail` loads; `ponytail-review`/`-audit` listed |
| frontend-design | OK | `frontend-design@claude-code-plugins` installed; `anthropic-frontend-design` skill present |
| UI/UX skill | OK, name is `uiux-pro-max` (also `uiux-design`, `uiux-design-system`, `uiux-styling`) | `~/.claude/skills/` |
| Graphify | OK | CLI 0.9.83; `docs/graph/` committed. Doc-semantic pass still not run |
| APIMatic PayPal context | **NOT INSTALLED** | not in `installed_plugins.json`. Per the apimatic/context-matic README: `/plugin marketplace add apimatic/context-matic`, `/plugin install context-matic@apimatic-context-matic`, `/reload-plugins`, `/mcp`; needs Claude Code >= 2.1.92. Covers "PayPal Server SDK" (orders, payments, vault); the README does not name a "PayPal REST API" entry. Interactive install, user must run it. |

### Astropods (check 9) — from docs.astropods.com
- Available: hosted platform, `ast` CLI. Availability tier (GA/beta/waitlist) not stated in docs.
- Auth: `ast login` = device flow (short code + URL, `--no-browser` supported); account required (signup at astropods.com/signup). Tokens in keyring or `~/.ast/credentials.json`. `ast whoami` verifies. No API-key flow documented.
- Free tier: **not stated**. Docs say a new personal account gets "one-time credits to spend before it needs a card"; usage limits page has pay-as-you-go spend caps that hard-stop all agents. Pricing not documented.
- Deploy: `ast spec validate` -> `ast blueprint push` -> `ast blueprint deploy` -> `ast agent list`. A blueprint = built container images + registered spec.
- Fit: a Python custom adapter exists (`pip install astropods-adapter-core`, Python >= 3.10, `agent.interfaces.messaging: true`), so deploying our agent is plausible but means wrapping it in Astropods' messaging adapter, not just pointing at the Render FastAPI. Telemetry from an agent hosted elsewhere is **not** supported: external telemetry accepts only official integrations (Claude Code listed). Docs do not say if arbitrary container images are accepted.
- Decision (provisional): treat Astropods as optional and cut-order item (spec 16). Day-1 verdict **blocked** until the user runs `ast login` and a trivial blueprint deploy succeeds. Fallback stays Render + own Elastic traces.

### Integration status
- PayPal/Kernel, catalog/Elastic, Modal/Qwen worktrees were still at `8f8b822` with no changes when checked; no reports to integrate. Day-1 checks 1-8 remain NOT RUN.
- A separate session is working on `feat/scoring-contracts` in the primary worktree (task/scoring contracts). Not merged; not reviewed.
