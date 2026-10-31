# Model/product deterministic boundaries

## Model calls

`agents.model.ModelAdapter` is the only model-facing core protocol. A request contains the pinned system prompt, complete message history, all nine Pydantic-derived tool schemas, sequence number, request ID, and optional seed. A response contains typed calls and measured token, latency, cost, finish-reason, model, checkpoint, retry, and seed-support metadata.

`QwenModelAdapter` understands the documented native `<tool_call>` JSON envelope. It accepts exactly one closed call per turn, rejects unknown tools and schema-invalid arguments, retries at most the configured bound, stores only SHA-256 of raw output, and raises `MalformedModelOutput` after failure. Modal loading/serving does not live in the episode runner.

`ScriptedModelAdapter` exercises the identical boundary. Its results are deterministic integration evidence, never a Qwen baseline.

## Grounded review signals

The lexical baseline loads the complete canonical ID set and complete product review text. A signal is emitted only when a configured phrase literally appears in cited text. Its artifact retains all input IDs, cited IDs, evidence phrases, method/version/time/content hash, persona relevance, polarity, confidence, automated verification, and independent sampled-human status.

Ratings and retrieval position are not evidence. Cross-product IDs, partial text retrieval, count/ID disagreement, unsupported phrases, and unverified review traps fail closed.

## Generations and payments

`world.orchestrator.run_generation` is model-backed and resumable. Checkpoint keys are `genome_id:task_id`; a completed key is loaded, not rerun. Full `EpisodeRecord` JSON is checkpointed so resumed summaries use the exact original result. The function constructs `MockPayments(auto_approve=True)` internally for every episode and has no sandbox-backend parameter.

Generation summaries expose counts and denominators for survivors, kills, hallucinations, refusals, review grounding, traps, budget violations, latency, cost, and mock captures. Any genome with an instant-kill episode is excluded from reproduction. Bottom-quartile culling, elitism, and deterministic mutation produce the next population.

## Judge authority

The fixed judge accepts semantic scoring inputs only. Its cache key binds pinned model, prompt version, and exact canonical input hash. Structured parse failure returns score zero and is cached. It records disagreement with deterministic facts but cannot change existence, category, price, budget, availability, provenance, or review-ID results. Evaluation-label fields are rejected from the request.

## Training and evaluation

Only non-killed, gate-passing, review-grounded survivor episodes from non-test, non-held-out tasks may enter curation. Runtime pending-order IDs are normalized for deduplication but original tool calls remain in SFT messages. Manifest v1.1 binds catalog, task/rule/model versions, episode/split provenance, normalized dedup hash, creation time, and content hash.

LoRA code in this branch is planning only. It requires at least one curated trace, a pinned base revision, explicit hyperparameters, a dated caller-supplied rate card, and an approved maximum cost. It cannot launch training.

Contender comparison refuses different task/seed multisets. Reports preserve numerator, denominator, exclusions, pass@k, variance, model-recorded latency, cost, checkpoint, memory setting, and training manifest identity. Empty denominators are `N/A`. WebShop remains unconfigured.
