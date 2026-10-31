# Deterministic core engine

## Invariants

1. Catalog facts are inputs; request prose is synthetic. Product, price, stock, attribute, and review facts are never generated.
2. Money is `Decimal`. Seeds are explicit on tasks, episodes, genomes, generations, mutation metadata, and checkpoints.
3. A hard constraint carries `ConstraintEvidence`. If a required constraint is not checkable, feasibility is **unknown**: the task has no feasible set, is not labeled impossible, and is ineligible for deterministic training.
4. A recommendation passes gate `G` only when the product exists, category/currency/catalog price match, the variant is available, the item is within the cap and feasible set, and source/as-of provenance exists.
5. Review claims carry IDs. IDs must exist under the selected product and must have appeared in review results before summarization.
6. Test and held-out tasks never enter memory or SFT curation. Killed, below-threshold, ungrounded, or invalid-review traces never enter either path.
7. Every attempted executed tool call records its action arguments, result references, summary/error, UTC timestamp, and contiguous sequence. Payment-guard rejection is retained as evidence.

## Task computation

`compute_feasible_set` applies exact category, maximum all-in price, positive variant inventory, and checkable attribute operators. Missing values fail a product; an explicitly uncheckable required field makes the whole task unsuitable.

Best value is transparent:

```text
price_headroom = max(0, (budget - price) / budget)
implied_fit = weighted mapped-attribute match rate, or 0.5 when no need is mapped
value_score = 0.7 * price_headroom + 0.3 * implied_fit
```

The highest score wins, with product ID as the stable tie-break. Split assignment hashes seed, task key, and category. Held-out categories bypass the percentage buckets. The leakage guard rejects duplicate task IDs and product overlap across protected test/held-out boundaries.

Review traps require at least one `ReviewSignal`, a distinct feasible review-adjusted best, and supporting review IDs that exist under the signaled product. Ratings alone cannot create a trap.

Production batch generation uses `FrozenTrainingCatalog`, not routed live search.
The contract requires complete deterministic enumeration and complete product-scoped
review IDs. `BatchConfig.feasible_percent` is constrained to 70–80; exact seeded
counts keep impossible tasks in the complementary 20–30 band. Amazon batches use
category and price only and reject variant/stock requirements.

## Action order

1. `parse_intent` is first and occurs once.
2. Search/lookup establishes discovered product IDs.
3. Product detail must be opened before review access or selection.
4. Comparison must include the configured minimum when enough discovered candidates exist.
5. Available reviews must be read before selection; summaries may cite only read, product-scoped IDs.
6. `propose_purchase` requires research, assumptions, a real opened product, and the guarded budget/price/variant checks.
7. `confirm_and_pay` requires an existing pending order plus explicit confirmation.
8. `report_no_match` requires a closest discovered product when any product was discovered, a miss reason, and assumptions.
9. Payment confirmation or no-match terminates the episode; later actions are invalid.

## Scoring

The score is:

```text
fitness = G * Q - efficiency_penalty
```

`Q` is an explicit weighted mean, never an opaque scalar. Components are intent extraction, mapped implied-needs fit, value reference, reviews consulted, review grounding, review-ID existence, persona signal recall, review-adjusted choice, review-trap choice, assumptions, no-match quality, and research sufficiency.

The efficiency penalty is capped at `0.20`. Insufficient research receives the cap, so skipping required calls can never improve fitness. Otherwise only calls beyond the configured baseline add penalty. A correct impossible-task refusal with the real closest product receives all deterministic quality components at 1. Semantic assumption or entailment accuracy can be supplied through the versioned, input-hashed, cached `Judge` protocol; parse failure closes at zero in the deterministic fake.

## Initial kill registry

| ID | Trigger |
|---|---|
| `K001_HALLUCINATED_PRODUCT` | Selected, closest, or proposed product absent from snapshot. |
| `K002_WRONG_REFUSAL` | No-match despite a non-empty feasible set. |
| `K003_BUDGET_VIOLATION` | Recommendation, proposal attempt, or payment exceeds the cap. |
| `K004_INSUFFICIENT_RESEARCH` | Pick not opened or too few candidates compared. |
| `K005_DUPLICATE_PAYMENT` | Same purchase/key produces distinct capture IDs; identical capture replay is safe. |
| `K006_FABRICATED_REVIEW_EVIDENCE` | Review ID missing or belongs to another product. |
| `K007_SKIPPED_REVIEWS` | A recommended product had reviews but none were consulted. |
| `K008_REVIEW_GAMING` | Limit-one, too-few, top-rating-only, generic, or persona-irrelevant reused evidence. |

Rules are stable, versioned, dated, enabled/disabled records with deterministic evidence. Loophole Hunter emits only `RuleCandidate(state="proposed")`. Confirmation requires an explicit version, reproducing test, and reviewer; only then is a rule enabled with affected episode IDs and kill count.

## Evolution and resume

Population initialization and all mutation use local seeded RNG instances. Genome hashes serialize every field except the external ID. Selection removes killed genomes, ranks survivors by fitness then ID, culls the bottom quartile, keeps all survivors unchanged as elites, and fills the population using seeded tournament parents. Mutations clamp temperature, search, and review parameters to schema ranges; prompt mutation uses a protocol and deterministic fixture proposer, not an LLM.

Checkpoint hashes cover the canonical JSON content. Episode keys are `genome_id:task_id`; resume schedules only absent keys, preventing duplicate work. Parent IDs always point to the supplied survivor population.

`world.orchestrator.run_generation` additionally requires the persisted episode set
to match completed checkpoint keys exactly. It internally constructs
`MockPayments(auto_approve=True)`, so world generations have no code path to PayPal
sandbox capture. A completed generation emits measured summaries, evaluation
JSON/Markdown, curated traces, and a versioned training manifest.

## Leakage and curation

- Memory refuses test requests and never stores test, killed, or negative-fitness episodes. Retrieval reapplies split, kill, threshold, deterministic ranking, and `k` limits.
- SFT curation excludes test/held-out, killed, gate-failed, review-ungrounded, and invalid-review traces.
- Normalized hashes use shopper text, typed actions, and final answer while ignoring episode/timestamp identity, so duplicate trajectories collapse deterministically.
- Manifests include catalog hash, task/rule versions, exact source episodes/splits, explicit creation time, and content hash.

## Evaluation

The harness accepts `EpisodeRecord` objects and task ground truth. Each metric exposes numerator, denominator, exclusions, unit, and optional value. Empty denominators are `N/A`, never zero. Seed variance is population variance over per-seed metric values when all seed denominators exist. JSON and Markdown render the same report. WebShop is a protocol stub and is not claimed complete.

## Fixture limitations

- Products/reviews under `tests/fixtures` are synthetic and marked test-only.
- In-memory catalog search treats an empty query as category enumeration; production providers must explicitly support or replace this contract.
- The current payment total equals catalog price. Providers with tax/shipping need a verified quote contract before use.
- Deterministic review checks prove ID existence/attribution, not natural-language entailment.
- Loophole positive-only sampling is strongest when complete ratings are available; the generic trace detector is conservative.
- No external catalog, memory store, model, judge, Elastic, Modal, PayPal sandbox, or paid API is invoked by this core.
