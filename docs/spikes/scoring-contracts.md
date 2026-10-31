# Scoring contracts spike

Status: implemented on `feat/scoring-contracts`. This spike defines contracts and
deterministic rules only. It does not generate production tasks, call a remote
catalog, invoke a judge model, or touch payment implementations.

## Boundary

- `tasks/schemas.py` defines the versioned ground-truth task envelope. A task is
  tied to one `catalog_snapshot_id`, and its `feasible_set` is an input that the
  future task generator must compute from that snapshot.
- `scoring/schemas.py` defines immutable, extra-forbidden episode traces, tool
  calls, outcomes, payment ledger events, gate results, quality evidence, and
  kill decisions.
- `scoring/gate.py` computes `G` from the task, trace, and injected
  `CatalogProvider`.
- `scoring/fitness.py` computes an explicit weighted `Q` with `Decimal`, then
  applies `fitness = G * Q - efficiency_penalty`.
- `scoring/kill_rules.py` evaluates every initial rule in stable registry order
  and returns all triggered decisions for auditability.
- `tests/fixtures/scoring.py` is synthetic, test-only data. Its records are not
  production products, reviews, or generated tasks and are marked with the
  source `synthetic-test-fixture`.

No production catalog schema is assumed beyond the existing `CatalogProvider`,
`Product`, and `Review` contract.

## Initial rule registry

| ID | Version | Deterministic trigger |
|---|---:|---|
| `K001_HALLUCINATED_PRODUCT` | 1 | A selected, closest, or proposed product ID is absent from the snapshot. |
| `K002_WRONG_REFUSAL` | 1 | The agent reports no match while `feasible_set` is non-empty. |
| `K003_BUDGET_VIOLATION` | 1 | A recommendation, proposal attempt, or payment event exceeds `max_total`. |
| `K004_INSUFFICIENT_RESEARCH` | 1 | A selected/closest item was not opened, or fewer than the required candidates were compared. |
| `K005_DUPLICATE_PAYMENT` | 1 | One product/variant or idempotency key has more than one distinct completed capture. |
| `K006_FABRICATED_REVIEW_EVIDENCE` | 1 | A cited review ID is missing from, or attributed to a different product than, the selected product. |
| `K007_SKIPPED_REVIEWS` | 1 | Reviews exist for a selected product but no returned review IDs appear in its `get_reviews` trace. |
| `K008_REVIEW_GAMING` | 1 | The trace uses a one-review query, consults too few available reviews, cites only top-rated reviews, uses a generic/no-concern claim, or reuses one review set across distinct concerns. |

Repeated observations of the same capture ID are treated as idempotent reads,
not duplicate charges. Distinct capture IDs trigger `K005`.

## Determinism and assumptions

1. The task and trace must have identical task and catalog snapshot IDs.
2. Catalog category matching is exact. Stock means the requested variant maps to
   an integer greater than zero. `expected_total` is assumed to be the all-in
   amount in the task currency.
3. `feasible_set` is authoritative for snapshot-derived hard constraints that
   are not represented by the current provider's generic product fields. The
   gate still independently checks existence, category, stock, and budget so
   failures have useful evidence.
4. Default research requirements are two compared candidates and two consulted
   reviews. They are task fields, so future versioned generation policy can set
   different thresholds without changing rule code.
5. Deterministic review grounding proves review-ID existence and product
   attribution. Claim-text entailment is intentionally not guessed here; the
   spec's fixed, cached judge must later contribute a separate quality metric.
6. Quality weights are explicit inputs carried by every `QualityMetric`. The
   spike does not invent global weights before evaluation policy is frozen.
7. Every contract is immutable and rejects unknown fields. Sequences must be
   unique and increasing, which makes serialization, replay, and test failures
   reproducible.
8. Rule evaluation is side-effect free assuming the injected catalog provider
   is read-only. The tests use only an in-memory implementation and perform no
   network or service calls.

## Integration requirements

- Task generation must run only after the production catalog schema and frozen
  snapshot are approved. It must compute `feasible_set`, best-value references,
  closest product for impossible tasks, and review signals from real snapshot
  records. No fixture in this spike may be promoted into a production task.
- The episode runner must emit the typed tool trace, including product IDs
  returned by `get_reviews`, comparison IDs, proposal amounts, variants, and
  idempotency keys. Without returned review IDs, grounding and skipped-review
  checks cannot distinguish a real read from an empty call.
- A snapshot provider used for validation must return the complete review-ID set
  needed for a product when called with `limit=10_000`, or the catalog contract
  must later gain a dedicated review-ID lookup. A silent provider cap would make
  uncached citations look fabricated.
- The payment adapter must normalize the ledger into `PaymentEvent` records and
  preserve capture IDs. Attempts rejected by the budget guard must still appear
  with status `attempted` or `failed` so `K003` can score the offense.
- The world runner should persist `rule_id` and `rule_version`, and should treat
  any non-empty `KillEvaluation.decisions` as an instant kill. Keeping every
  decision, rather than only the first, supports the dashboard and loophole-rule
  impact analysis.
- The fixed judge/cache layer must provide auditable `QualityMetric` evidence
  for semantic implied-needs and entailment judgments. Deterministic metrics can
  use the same contract.
- Packaging must add `tasks` and `scoring` to the project package list when the
  owner of shared `pyproject.toml` integrates this branch. This spike leaves that
  shared file untouched as required.

## Reproducible checks

Run the focused contracts and the full repository suite without external
services:

```bash
UV_CACHE_DIR=/tmp/crucible-uv-cache uv run pytest -q \
  tests/test_task_schemas.py tests/test_scoring_gate.py \
  tests/test_scoring_fitness.py tests/test_kill_rules.py
UV_CACHE_DIR=/tmp/crucible-uv-cache uv run pytest -q
```
