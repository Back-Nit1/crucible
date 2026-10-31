# Day-1 checks 5–6: Qwen tool calling and Modal resumability

Date: 2026-10-31

Seed: `20261031`
Status: **no-go for Qwen promotion; Modal Volume resume proof passed**

This spike is deliberately independent of the unfinished agent runtime. It does
not train a model and does not claim fine-tuning success.

## Outcome

| Check | Result |
|---|---|
| Modal authentication | Passed with `modal token info` output suppressed; no credential value was logged |
| Model license | Apache-2.0; fine-tuning and conservative adapter redistribution are permitted subject to the license conditions below |
| Exact checkpoint | `Qwen/Qwen2.5-7B-Instruct@a09a35458c702b33eeacc393d103063234e8bc28` |
| Smallest suitable probe GPU | One NVIDIA L4 (24 GB); T4 (16 GB) is too tight for the 15.2 GB bfloat16 artifact plus runtime/KV overhead |
| Preflight cost ceiling | `$0.861948` for the hard 45-minute L4 + 2 CPU core + 32 GiB RAM limit |
| GPU execution | Blocked before allocation: Modal requires a payment method for L4 functions |
| GPU spend | `$0.00` |
| Structured-call metrics | Not measured; reporting invented or CPU-substitute values would violate the Day-1 check |
| Volume resume | Passed: stopped after saved step 3; fresh invocation resumed at 3 and completed 4–6 |
| Resume wall time | `13.901644s` across stop, inspection, resume, and final inspection |

Raw sanitized results are in
[`eval/results/day1_qwen_tool_calls.json`](../../eval/results/day1_qwen_tool_calls.json)
and
[`eval/results/day1_modal_resume.json`](../../eval/results/day1_modal_resume.json).

## Model and license verification

The selected checkpoint is
[`Qwen/Qwen2.5-7B-Instruct`](https://huggingface.co/Qwen/Qwen2.5-7B-Instruct/tree/a09a35458c702b33eeacc393d103063234e8bc28),
pinned to full Hugging Face commit
`a09a35458c702b33eeacc393d103063234e8bc28`. The repository labels the model
Apache-2.0 and the pinned repository contains the
[`LICENSE`](https://huggingface.co/Qwen/Qwen2.5-7B-Instruct/blob/a09a35458c702b33eeacc393d103063234e8bc28/LICENSE).

Apache License 2.0 section 2 permits reproducing and preparing derivative works;
section 4 permits redistribution of the work or derivative works, modified or
unmodified. Therefore fine-tuning is permitted. For adapter redistribution,
Crucible should conservatively treat the adapter as a derivative work and:

- include a copy of Apache-2.0;
- state that the adapter modifies/derives from the pinned Qwen checkpoint;
- retain applicable copyright, patent, trademark, and attribution notices;
- include applicable `NOTICE` content if a future pinned revision contains one;
- use Qwen/Alibaba names only for customary source attribution, not endorsement.

This is a technical license review, not legal advice. No adapter was created or
distributed in this spike.

Qwen's official
[`Function Calling`](https://qwen.readthedocs.io/en/v2.5/framework/function_call.html)
guide confirms that Qwen2.5's tokenizer contains a Hermes-style tool-use template,
accepts JSON Schema tools through `apply_chat_template`, and emits JSON inside
`<tool_call>` tags. It also explicitly warns that malformed JSON and
schema-invalid arguments can occur, which is why those are separate metrics.

## Tool contract

The executable schemas live in
[`eval/day1_tool_calling.py`](../../eval/day1_tool_calling.py). Every input object
uses `additionalProperties: false`; identifiers and user text must be non-empty;
prices are non-negative; review sort is an enum; and comparison requires at least
two unique products.

| Tool | Required arguments |
|---|---|
| `parse_intent` | `raw_message`; description requires it to be the first call |
| `search_catalog` | `query`, typed `filters` |
| `get_product` | `product_id` |
| `compare` | `product_ids` (2+ unique IDs) |
| `get_reviews` | `product_id`, `sort`, `limit`; optional `focus` |
| `summarize_review_evidence` | `product_id`, typed `user_context` |
| `propose_purchase` | `product_id`, `variant`, `expected_total` |
| `confirm_and_pay` | `pending_order_id` |
| `report_no_match` | `reason`, `closest_product_id`, `why_it_misses` |

The probe performs only the required first turn: the system prompt requires one
`parse_intent` call and forbids any other first-response tool. It does not fake
catalog responses, product IDs, reviews, orders, or payment results.

## Seeded prompt suite and metrics

The 20 prompts are generated in a deterministic order from seed `20261031`.
Manifest SHA-256:
`b7445bb3195e10959504dc2e4262940eb69cac9d8a96b6c600b90566c9973f38`.
The bank contains 15 feasible scenarios, 5 intentionally impossible scenarios,
5 ambiguous scenarios, and 8 review-sensitive scenarios. These labels describe
the requested scenario mix; they are not a claim about an unfinished catalog.

Metric definitions:

- **valid structured-tool-call rate:** tasks with at least one syntactically valid
  Qwen tool-call envelope divided by 20;
- **schema-valid argument rate:** calls whose name exists and whose arguments pass
  that tool's schema divided by all syntactically parsed calls;
- **parse_intent first:** tasks whose first parsed call is `parse_intent` divided
  by 20;
- **nonexistent tool calls:** count of parsed calls whose names are absent from the
  nine-tool contract;
- **malformed JSON:** count of malformed or unclosed `<tool_call>` JSON blocks;
- **latency:** per-task synchronized CUDA generation time, plus total/mean/p50/p95;
- **cost:** measured function runtime multiplied by current L4, requested CPU, and
  requested memory list rates.

Because GPU registration was rejected before allocation, all model-dependent
values below are honestly recorded as not measured.

| # | Task | Class / traits | Structured | Schema | Parse first | Unknown | Malformed | Latency |
|---:|---|---|---|---|---|---|---|---|
| 1 | `office-chair` | feasible, review | N/M | N/M | N/M | N/M | N/M | N/M |
| 2 | `keyboard-quiet` | feasible, ambiguous, review | N/M | N/M | N/M | N/M | N/M | N/M |
| 3 | `gpu-1440p` | feasible, ambiguous | N/M | N/M | N/M | N/M | N/M | N/M |
| 4 | `bottle-commute` | feasible | N/M | N/M | N/M | N/M | N/M | N/M |
| 5 | `impossible-gpu` | impossible | N/M | N/M | N/M | N/M | N/M | N/M |
| 6 | `desk-small` | feasible, ambiguous | N/M | N/M | N/M | N/M | N/M | N/M |
| 7 | `impossible-book` | impossible | N/M | N/M | N/M | N/M | N/M | N/M |
| 8 | `shoe-heavy-10k` | feasible, ambiguous, review | N/M | N/M | N/M | N/M | N/M | N/M |
| 9 | `impossible-free-shoe` | impossible | N/M | N/M | N/M | N/M | N/M | N/M |
| 10 | `impossible-contradiction` | impossible, ambiguous | N/M | N/M | N/M | N/M | N/M | N/M |
| 11 | `switch-coop` | feasible | N/M | N/M | N/M | N/M | N/M | N/M |
| 12 | `monitor-photo` | feasible | N/M | N/M | N/M | N/M | N/M | N/M |
| 13 | `impossible-chair` | impossible | N/M | N/M | N/M | N/M | N/M | N/M |
| 14 | `lamp-study` | feasible | N/M | N/M | N/M | N/M | N/M | N/M |
| 15 | `student-laptop` | feasible, review | N/M | N/M | N/M | N/M | N/M | N/M |
| 16 | `hike-wide-rain` | feasible, review | N/M | N/M | N/M | N/M | N/M | N/M |
| 17 | `anc-flight` | feasible, review | N/M | N/M | N/M | N/M | N/M | N/M |
| 18 | `ssd-upgrade` | feasible, review | N/M | N/M | N/M | N/M | N/M | N/M |
| 19 | `textbook-used` | feasible, ambiguous | N/M | N/M | N/M | N/M | N/M | N/M |
| 20 | `jacket-packable` | feasible, review | N/M | N/M | N/M | N/M | N/M | N/M |

## GPU choice, cost, and LoRA estimate

Modal lists T4, L4, A10, and larger accelerators in its
[`GPU guide`](https://modal.com/docs/guide/gpu). NVIDIA specifies
[`16 GB` for T4](https://www.nvidia.com/content/dam/en-zz/Solutions/Data-Center/tesla-t4/t4-tensor-core-datasheet-951643.pdf)
and
[`24 GB` for L4](https://www.nvidia.com/content/dam/en-zz/Solutions/Data-Center/l4/PB-11316-001_v01.pdf).
The pinned bfloat16 model repository is 15.2 GB before framework allocations and
KV cache, so T4 is not a safe unquantized target. L4 is the smallest suitable
unquantized inference probe and is cheaper than Modal's A10.

The current
[`Modal pricing page`](https://modal.com/pricing) lists L4 at `$0.000222/s`, CPU
at `$0.0000131/core/s`, and memory at `$0.00000222/GiB/s`. The function requests
one L4, 2 physical CPU cores, and 32 GiB memory with a 2,700-second timeout:

| Resource | 45-minute ceiling |
|---|---:|
| L4 | `$0.599400` |
| CPU | `$0.070740` |
| Memory | `$0.191808` |
| **Total** | **`$0.861948`** |

This excludes any credits and is below the `$5` cap. Actual GPU spend is `$0`
because allocation never occurred. The small CPU resume job is comfortably below
one cent by list-rate estimation; Modal billing remains the source of truth.

For later LoRA work, L4 is a plausible **QLoRA** development target with a small
micro-batch, gradient checkpointing, and optimizer-state discipline. Qwen's
official
[`LLaMA-Factory training guide`](https://qwen.readthedocs.io/en/v3.0/training/llama_factory.html)
lists LoRA and QLoRA support for Qwen2.5. A 24 GB L4 is not a defensible default
for unquantized 7.6B LoRA SFT once weights, gradients, optimizer state, activations,
and sequence length are included; use A100-40GB or validate QLoRA memory first.
No training allocation or throughput measurement was made here.

GPU availability and cold-start time remain **not measured**: Modal supports L4,
but its official guide requires a valid payment method for GPU use, and this
workspace was rejected at that prerequisite before scheduling.

## Checkpoint/resume evidence

The probe follows Modal's documented
[`Volume`](https://modal.com/docs/guide/volumes) and
[`long resumable job`](https://modal.com/docs/examples/long-training) pattern:
commit a checkpoint periodically, reload the Volume in a new invocation, and
continue from the latest state.

Observed run `day1-1793478956`:

1. invocation A committed steps 1, 2, and 3 to a v2 Volume;
2. invocation A intentionally terminated immediately after committing step 3;
3. an independent inspection saw `latest.step == 3`;
4. invocation B reloaded the Volume and reported `resumed_from_step == 3`;
5. invocation B committed steps 4, 5, and 6;
6. final history was exactly `[1, 2, 3, 4, 5, 6]`, with no duplicate or gap.

This proves the minimal checkpoint primitive. It does not prove that a future
trainer serializes every required optimizer/scheduler/RNG state; that must be a
separate training-pipeline test.

## Reproduction

Use Modal's documented credential check without printing token information:

```bash
modal token info >/dev/null 2>&1
```

Local deterministic tests:

```bash
UV_CACHE_DIR=/tmp/crucible-uv-cache uv run pytest -q
```

Volume stop/resume probe:

```bash
uv run modal run modal_app/day1_probe.py::checkpoint_resume_probe
```

After adding a valid Modal payment method, rerun authentication and the bounded
GPU probe:

```bash
CRUCIBLE_ENABLE_L4_PROBE=1 \
  uv run modal run modal_app/day1_probe.py::tool_call_probe
```

The local entrypoint rechecks the `$0.861948` hard ceiling before calling the
remote function. It writes raw model outputs, token counts, per-task latency,
hardware observations, and aggregate metrics to the sanitized result JSON.

## Recommendation and blocker

**No-go for Day-1 check 5** until the L4 probe produces real metrics. Do not build
the training pipeline or promote this checkpoint based only on schema/template
support. **Go for the minimal Day-1 check 6 Volume primitive**; carry it into the
world/training design, then separately validate complete trainer-state recovery.

Blocker: add a valid payment method to the authenticated Modal workspace. Then
run only the bounded command above; its worst-case list-price estimate remains
under `$1`, so no additional spend approval is required under the `$5` cap.
