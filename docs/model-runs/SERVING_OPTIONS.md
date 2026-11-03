# Qwen serving options through December 15

Status on 2026-11-02: **decision not made; nothing is deployed; measured cold-start time is Not run; spend is $0.**
These are operating choices for the user, not a recommendation or a claim that free credit is available.

## Fixed deployment facts

`modal_app/qwen_inference.py` requests one L4, 2 physical CPU cores, and 32 GiB memory. It currently sets
`max_containers=1`, `scaledown_window=60`, and leaves `min_containers` unset (equivalent to zero). The model is baked into
the image; final adapters live on a Modal Volume. The client allows at most 256 new tokens and has a 120-second call
timeout. A shopping episode is already bounded to 20 model/tool steps.

Modal documents that `min_containers=0` permits scale-to-zero, while a positive value keeps paid containers warm. It
also says the default idle window is billable and that a Workspace budget is the hard outer usage cap; a separate spend
limit caps net charges after credits. Sources: [pricing](https://modal.com/pricing),
[cold starts](https://modal.com/docs/guide/cold-start), [budgets](https://modal.com/docs/guide/budgets), and
[GPU requirements](https://modal.com/docs/guide/gpu).

Cold-start time for this exact Qwen image on an L4 is **Not measured**. Stage A must record it from real response metadata
before any latency promise is published. It includes container scheduling plus loading 15.2 GB of model weights into GPU
memory. Do not substitute a generic Modal cold-start number.

## Cost model (list-rate scenarios, not measured spend)

Official list rates on 2026-11-02 are L4 `$0.000222/GPU-second`, CPU `$0.0000131/core-second`, and memory
`$0.00000222/GiB-second`. For the requested 1 L4 + 2 cores + 32 GiB, the arithmetic rate is:

`0.000222 + (2 × 0.0000131) + (32 × 0.00000222) = $0.00031924/second`.

| Billable container time | Compute at list rate | What it illustrates |
|---:|---:|---|
| 1 second | $0.00031924 | Unit rate for this configuration |
| 10 seconds | $0.00319240 | Example short generation; not a latency claim |
| 60 seconds | $0.01915440 | One full configured idle window |
| 5 minutes | $0.09577200 | Short judge/demo burst |
| 1 hour | $1.14926400 | Warm-container hourly cost |
| 30 days continuously warm | $827.47008000 | Why `min_containers=1` is not a low-cost default |

A purely illustrative 20-call session at 3 seconds per call plus one 60-second idle window is 120 billable seconds, or
`$0.03830880`. The 3-second assumption is **unmeasured** and excludes a cold load, retries, storage, and network charges.
Actual Modal billing is authoritative. Modal currently advertises `$30/month` of compute credit on Starter, but this
project must not call service free unless the dashboard confirms unused applicable credit.

## Options for the user

| Option | Availability to judges | Latency | Cost control | Trade-off |
|---|---|---|---|---|
| A. Deployed L4, scale to zero | Endpoint remains deployed; first request after idle starts a container | Cold start **Not measured**; later calls in the 60-second window avoid a fresh load | `min_containers=0`, `max_containers=1`, Workspace budget + net spend limit | Lowest idle cost; first request can time out or return unavailable while starting |
| B. Scheduled warm windows | Warm only during announced demo/judging windows; scale to zero otherwise | Avoids cold starts inside the window | Temporarily set `min_containers=1`; restore zero immediately after | About $1.149264/hour at current list rates; judges may arrive outside the window |
| C. Continuously warm L4 | Most predictable availability | Container-load delay avoided while healthy | Hard monthly cap still required | Not “very cheap”; the 30-day scenario above is unacceptable without explicit approval |
| D. Scale-to-zero plus typed degraded mode | Web/API stay available even when model capacity is unavailable | UI gets an immediate typed failure instead of a fabricated answer | Same as A; no fallback model spend | Shopping inference is unavailable during a cold-start failure or exhausted cap |

CPU fallback is not an option: the deployed service intentionally refuses to load this 7B model without CUDA. A paid
frontier-model fallback is also out of scope and has no authorization.

## Required abuse and spend guardrails

Before leaving Option A, B, or C accessible, the API owner must add and test these candidate caps (they are **not
implemented** as of this document):

- at most 12 new shopping sessions per source IP per hour and 2 concurrently active sessions per IP;
- at most 20 model calls per session (already enforced in the buyer/agent runtime; retain it at the API boundary);
- one active request per session, rejecting duplicate concurrent submits with a typed rate-limit response;
- `max_containers=1`, 256 output tokens per call, and the existing client cost ceiling;
- a Workspace budget and net spend limit chosen by the user in Usage & Billing. The application ceiling is an additional
  guard, not a replacement for Modal's hard account-side cap.

The IP thresholds need a documented judge bypass because corporate NAT can group judges behind one address. The bypass
must raise access, not remove the per-session 20-call cap.

## Degraded behavior

The existing API returns HTTP 503 with error code `model_unavailable` when no model is configured, and maps inference
timeouts/transport failures to the same typed condition. The UI should preserve the shopping request, say the model is
temporarily unavailable, allow a bounded retry, and never substitute scripted recommendations or cached purchases.
Reaching the application ceiling or Modal Workspace budget must use this path.

## Decision checklist

- Choose A, B, C, or D and record the choice in `DECISIONS.md`.
- Confirm the Workspace budget and net spend limit in Modal; do not write their values into source code.
- Complete Stage A and replace “Not measured” only with the saved probe's real cold-start and generation measurements.
- Have Agent A implement the IP/session caps before a public endpoint is left running.
- Verify the endpoint from a clean judge session, then keep the selected mode available through 2026-12-15.
