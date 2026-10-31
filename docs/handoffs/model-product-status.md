# Model, evaluation, and product status

Branch: `feat/model-training-product`

Base: Agent 1's verified integration head `9e01481` (the shared `main` ref was still stale at branch creation). Baseline: `200 passed, 2 live deselected`. Final deterministic phase gate: `231 passed, 2 live deselected, 1 existing Starlette/httpx deprecation warning`.

No secret value was read or printed. No paid API, Modal GPU, PayPal sandbox capture, model training, model weight, or checkpoint was created. World runs construct `MockPayments` internally.

## Phase status

| Phase | Status | Evidence / blocker |
|---|---|---|
| 1. Real task batches | Deterministic core complete | `tasks.batch` uses only `SnapshotCatalog.iter_products`; exact configurable 70-80% feasible mix, review-trap target, difficulty mix, held-out categories, product-disjoint split projections, batch/task hashes, and fail-closed verified-trap requirements. Generated constraints are category/price only. |
| 2. Real review signals | Lexical baseline complete | Versioned literal-phrase extraction records canonical input/cited IDs, method/version/time/content hash, persona relevance, confidence, automated verification, and separate sampled-human status. Complete product-scoped ID lookup and full text retrieval fail closed. Fixed-model extraction is blocked on the Qwen probe. No real signal is described as human-approved. |
| 3. Model adapter | Complete boundary | Vendor-neutral structured `ModelAdapter`, model metadata, deterministic `ScriptedModelAdapter`, `AdapterPolicy`, and `QwenModelAdapter` over an injected inference client. Native tool envelopes are schema-validated; malformed output is hashed, bounded-retried, and rejected without retaining raw output. |
| 4. Qwen 20-prompt probe | Blocked, not run | Agent 1 measured `$0` spend because Modal rejected L4 allocation until a payment method is added. The rotated token is not confirmed. Existing sanitized results correctly remain “not measured.” |
| 5. Generations | Scripted fixture complete; real/Qwen incomplete | New world orchestrator is checkpointed, duplicate-free, model-backed, memory-aware, and MockPayments-only. Agent 1's prior real-snapshot scripted run scored 36/40 pairs, skipped 4 unscriptable pairs, had 0 kills, selected 3 survivors and bred 4 next genomes; the scripted policy reads reference answers and is not a model result. Base Qwen and Qwen+memory are blocked by phase 4. |
| 6. Fixed judge | Complete boundary | Pinned model/prompt, exact canonical input hash, deterministic cache key, structured parse, 0-2 retries, latency/cost/disagreement, cached failures, forbidden test-label fields, and score-zero fail-closed behavior. No invoker is configured. |
| 7. Training/LoRA | Curation and planning complete; training blocked | Manifest v1.1 adds source model, episode/split provenance, normalized dedup hash, and content hash. Cost plans require dated caller-supplied rates and an approved ceiling. No LoRA was launched because no Qwen survivor set exists. |
| 8. Evaluation | Harness and comparison complete; model numbers unavailable | Identical task/seed enforcement, checkpoint/manifest identity, pass@k, held-out metrics, model-recorded latency, cost, variance, and JSON/Markdown writers. Only scripted fixture numbers exist. WebShop remains an explicit stub. |
| 9-12. Web product | Blocked before implementation | Required `frontend-design` and UI/UX skills are absent from this Codex session, and the merged repo has no `web/` package or frontend dependency manifest. Shared dependency changes are outside this branch. Real generation is not green, so WebShop also remains stubbed. |

## Reproducible scripted fixture generation

This is integration evidence over explicitly synthetic test products/reviews, not model quality and not a real-catalog metric.

- Seed: `91`
- Population/tasks/episodes: `4 / 3 / 12`
- Task mix: feasible, impossible, and verified lexical review trap
- Survivors: `3`; next generation: `4` with a mutated child
- Kills by rule: none
- Hallucinations: `0/12`
- Wrong refusals: `0/8`; correct refusals: `4/4`
- Review grounding: `12/12`; review-trap accuracy: `4/4`
- Budget violations: `0/12`
- Mock captures: `8`; external payment captures: `0`
- Model latency/cost: `0 ms / $0` (deterministic adapter)
- Evaluation: success `12/12`, hard-constraint satisfaction `12/12`, pass@1 `3/3`, persona review recall `2/3`, held-out category `N/A`
- Survivor SFT records after deterministic deduplication: `3`
- Fixture training manifest: `c6e9bb82f159cfdeb02231b1c7e6f8effe476e823ac61c2fd6394315afdb578e`
- Fixture deduplication hash: `fd78cd43e689f59527142f289727244cc8e451b75632dfe7496a416fd5e4368b`
- Fixture catalog hash is deliberately `"a" * 64`; it is not a real catalog manifest.

## Real snapshot evidence already integrated from Agent 1

Manifest-only fixtures verify four Amazon Reviews 2023 category snapshots: 590 products and 14,541 canonical collision-safe review IDs. No raw review dataset is committed. Agent 1's live scripted generation is pipeline evidence only: 40 requested pairs, 36 scored, 4 search-unscriptable, 0 duplicate trace IDs, 0 kills. It cannot be used to claim Qwen quality, memory uplift, or training readiness.

## Platform contracts required from Agent 1

1. Implement `agents.model.QwenInferenceClient` in the runtime layer. It must accept the exact system prompt, messages, tool schemas, request seed and retry index, and return raw native Qwen output plus token counts, latency, finish reason, pinned model/checkpoint, seed support, and measured cost. The core adapter retains only the raw-output hash.
2. After the user adds Modal billing and confirms the rotated token, expose the existing bounded Qwen probe through that same inference contract. Do not raise the existing `$0.861948` ceiling without approval.
3. Expose the frozen snapshot directly as `SnapshotCatalog` to the task/review workflow, plus stable snapshot ID, combined catalog manifest hash, and configured category enumeration. `TrainingCatalog` currently hides `review_count` and direct `review_ids`; episode grounding bridges through its router, but extraction should not depend on wrapper internals.
4. Add a backend agent/chat endpoint that returns API-owned schemas for parsed intent, assumptions, research events, grounded product cards, no-match, quote, explicit confirmation, approval URL/status, capture receipt, and actionable error states. The current API exposes catalog and purchase primitives only.
5. Add read-only API contracts for generation summaries, agents, kills, episodes/tool replay, mock/sandbox ledger, lineage, Loophole Hunter timeline, and evaluation contender reports. Every number must carry source/version metadata.
6. Bootstrap `web/` and its locked Next.js/Tailwind/AG Grid/testing dependencies in shared dependency files, then make the required frontend-design and UI/UX skills available to this agent before UI implementation.
7. Provide PayPal sandbox buyer credentials only through the runtime environment if Kernel-approved capture is required. Population/world runs must continue to reject sandbox backends.

## Remaining blockers and decisions

- Modal payment method and rotated-token confirmation block Qwen inference, the fixed-model review extractor, real base/memory generations, cost measurement, LoRA, and held-out before/after evaluation.
- No grounded Qwen survivor traces exist, so training would violate the evidence gate.
- The current 48 real tasks include five protected-split feasible-set overlaps. Product-type subcategories or another disjoint task projection must replace broad category tasks before held-out evaluation.
- Real review-signal extraction still needs versioned category/persona lexical rules and sampled human review. Retrieval rank and ratings cannot create signals.
- PayPal buyer credentials block the judge-facing sandbox approval/capture path. They are unrelated to world generations, which remain mock-only.
- Frontend implementation is blocked as described above. No routes or screenshots are claimed.
- WebShop is not executable and remains labelled a stub.

## Next safe sequence

1. User adds Modal billing and confirms the rotated token; run the single bounded 20-prompt probe.
2. If probe quality passes, run a small base-Qwen real batch, then the identical batch with memory; report all denominators and cost.
3. Extract and sample-review real lexical signals; build verified review traps only from accepted evidence.
4. Curate grounded Qwen survivors, manually inspect the deterministic sample, estimate dated cost, and request budget approval before one small LoRA job.
5. Evaluate base/base+memory/fine-tuned+memory on identical held-out pairs. Claim improvement only if those results demonstrate it.
6. Agent 1 supplies web/API bootstrap and required skills; then implement chat, World, and Model surfaces against real schemas.
