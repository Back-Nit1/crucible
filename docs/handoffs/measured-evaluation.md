# Measured evaluation (Agent 2) — branch `feat/measured-evaluation`

Base: `origin/main` @ `11fcb1f`. **No real model evaluation has run.** Everything below marked *built* is offline-tested; everything
marked *blocked* names the exact missing requirement. Spend: **$0** (no Modal, no frontier model, no PayPal).

## Status
| Area | State |
|---|---|
| Run manifest (`eval/manifest.py`): versioned, canonical hash, exact task order + seeds, contender identities, status, resume info | **built**, tested |
| Contenders (`eval/contenders.py`): placeholders rejected, 40-hex revision, adapter+training hashes required for fine-tuned, frontier needs explicit spend authorization | **built**, tested |
| Leakage audit (`eval/leakage.py`, `scripts/audit_split_leakage.py`): 8 checks, `not_run` never counts as pass | **built**, tested |
| Product-disjoint task set (`eval/taskset.py`, `scripts/build_eval_taskset.py`) + committed set `docs/evaluations/taskset-20261110` | **built, audit passes** |
| Runner (`eval/runner.py`): identical matrix, atomic per-record artifacts, resume without duplicates, bounded concurrency, circuit breaker + quarantine, finalize refuses partial runs | **built**, tested with a model double |
| Frozen read-only memory (`eval/memory.py`) | **built**, tested |
| Metrics (`eval/harness.py`): numerator/denominator/excluded/unit/failure reasons/seed variance; latency+cost only from recorded model metadata | **built**, tested |
| Report (`eval/report.py`): JSON + Markdown, paired-vs-base, WebShop or explicit not-run, evidence class | **built**, tested |
| Publish (`eval/publish.py::measured_docs`, `trained_checkpoint_doc`): idempotent, refuses doubles/failed audit/incomplete/unvalidated adapter | **built**, tested against a fake ES; **nothing published** |
| WebShop (`eval/webshop.py`, `eval/webshop_driver.py`) | **adapter built and tested** (fake env + real subprocess protocol test); **blocked_not_run** — benchmark not installed |
| Base Qwen / Qwen+memory / fine-tuned measurements | **blocked** (below) |
| Frontier ceiling | not authorized, not configured |

## Split-leakage finding (the "5 protected-split overlaps")
Root cause: `world.taskgen.generate_tasks` computes every task's feasible set over the **whole category**, then labels it train/val/test by
hash. A test task (budget $40) and a train task (budget $60) therefore share every product under $40. `tests/test_eval_leakage.py::
test_world_taskgen_whole_category_tasks_leak_across_splits` reproduces this (product-overlap check fails). `tasks.batch.generate_batch` already
filters each split's pool to that split's own products, so `eval.taskset.build_eval_taskset` builds on it (plus verified review-trap plans) and
the audit confirms zero overlap. **No exclusion list papers over overlaps**; the only drops are exact text duplicates (5 of 52, listed with the id each
duplicates in `exclusions.json`). Why that is valid: the rule reads only the normalized request text, never difficulty, ground truth or any outcome, so it
cannot select easy or hard tasks; a text-identical pair is the same query counted twice or a prompt the model may have seen in training.

Committed set `docs/evaluations/taskset-20261110` (seed 20261110, real frozen snapshot, read-only Elastic): 47 protected tasks
(32−dups test, 20−dups held-out `Sports_and_Outdoors`; 8 impossible, 4 review-trap) and 28 train/val reference tasks. `tests/test_eval_committed_taskset.py`
asserts: audit passes against `data/manifests`, protected products ∩ train/val products = ∅, test ∩ held-out = ∅, held-out category absent from train/val.

Two other findings:
1. **Training must use the reference tasks.** Existing generation (`scripts/run_generation.py` + `world.taskgen`) still produces whole-category tasks.
   Until generation/training consume `docs/evaluations/taskset-20261110/reference.jsonl` (or any task set that passes `audit` against the protected
   set), a fine-tuned run can leak. `audit_split_leakage --training-manifest` is the gate; I did not edit `scripts/run_generation.py` or `world/**`.
2. **Memory on protected tasks was a no-op.** `RepositoryMemoryProvider.retrieve` returns `()` for test/held-out *queries*, so base+memory == base on exactly
   the evaluation tasks. `FrozenEvalMemory` answers protected queries from an audited, read-only pool (never protected splits, scripted traces, evaluation
   tasks, or recommendations of evaluation products). Memory-contender planning is refused without a non-empty pool; evaluation episodes never enter memory.
   (A `products_considered` check was rejected: search hits span the whole category and are not answers.)

Also fixed narrowly in `tasks/batch.py::_eligible_trap`: it could select a review-trap plan whose alternative was the cheapest feasible product, which
crashed later in `build_review_trap`; eligibility now skips such plans.

## Metrics honesty changes (`eval/harness.py`)
- `latency_ms` previously fell back to `ended_at − started_at`, which is a synthetic 1 s/tick clock. Now only recorded `latency_ms` model metadata counts;
  others are excluded (`no_model_latency_recorded`).
- `cost_per_task` excludes episodes with `cost_known=False` (previously counted as 0). Unit is `mean_usd_list_rate_estimate`; Modal billing is authoritative.
- Success rate lists `termination:*` / `kill:*` / `gate_failed` reasons. Variance is population variance across the seeds in `report.seeds`; `None` with one seed.
- Published docs also carry the keys `web/` reads: `contender`, `status`, `seeds`, `pass_at_k`, `latency_ms`, `cost_per_task_usd`, `variance`.

## Scripted shoppers
`EvaluationManifest` contenders are model contenders only (`base|finetuned|frontier`); the runner always uses `AdapterPolicy`. `build_report` raises
`NotAMeasurement` if any episode's model metadata says `scripted` unless `--allow-test-double`, which stamps `evidence_class: test_double_not_a_measurement`;
`measured_docs` refuses anything but `measured_model`. Tests use a scripted double that reads answer keys: they check machinery, never quality.

## WebShop
Source: <https://github.com/princeton-nlp/WebShop>, **MIT**, pinned to `64fa2a5c15c7daa698b9ac93f5bb5437b634c9bd` (master HEAD 2026-11-01).
Method (from that revision's `baseline_models/test.py`): `env.reset(session=i)` for `i in range(500)`, ≤100 `search[...]`/`click[...]` actions, final reward in [0,1]
(×100 in the paper). Requirements (README + `setup.sh`): Python 3.8.13 conda env, `./setup.sh -d small|all` (pip deps, `gdown` data from Google Drive, spaCy
`en_core_web_lg`, Pyserini/Lucene index needing JDK 11); Apple silicon uses `README_INSTALL_ARM-MAC.md`. Nothing is vendored. The hosted HF Space is **not** used.
Adapter: `SubprocessWebShopEnv` runs `eval/webshop_driver.py` under the WebShop interpreter (JSONL, WebShop's stdout noise redirected); `ModelWebShopAgent`
maps a contender onto `search`/`click` through the same pinned inference client (checkpoint pinned per request); backend errors are *excluded*, a real
no-purchase ending is a real 0 (`step_limit`); transcripts are hashed and kept out of git. A subset of sessions is labelled `full_benchmark: false`.
Current result: **`blocked_not_run`** — this machine has no WebShop clone/env (`WEBSHOP_HOME`, `WEBSHOP_PYTHON`), data, index, or Python 3.8; JDK 25 is installed
(WebShop's setup pins JDK 11). Exact commands are in `eval/webshop.py::SETUP_COMMANDS` and the blocked result JSON.

## Interface expected from / assumed about Agent 1
`modal-training.md` says: trained checkpoint label `qwen-lora-<adapter_hash[:12]>`; manifest `<volume>/<run_id>/final/artifact_manifest.json`
(`crucible-adapter-v1`); wire request gains optional `adapter {run_id, adapter_hash, training_manifest_hash}`. Not on `origin/main` yet, so **not integrated**.
`eval.contenders.AdapterReference` (adapter_ref, adapter_sha256, base_model, base_revision, training_manifest_hash) is the neutral shape; when their
`training.checkpoints` lands, add a ~10-line `AdapterReference.from_artifact_manifest` and have `run`'s model factory build a client for the
adapter. Until then `run` exits 3 for any plan with a fine-tuned contender: there is no silent fallback to the base model, and every request pins
`request_checkpoint` (`qwen-lora-…` or the base revision), which the client must refuse if it cannot serve.

## Blockers (exact)
1. Modal: `CRUCIBLE_MODAL_TOKEN_ROTATED=1`, `CRUCIBLE_MODAL_BILLING_CONFIRMED=1`, `CRUCIBLE_MODAL_APPROVED_CEILING_USD=<amount>` (not in the env file), a workspace payment
   method, and a deployed `modal_app/qwen_inference.py`. Needed for base-qwen at all.
2. Memory contender: a pool of **real model** (non-`scripted*`) traces from reference tasks only (`--memory-pool pool.jsonl`).
3. Fine-tuned contender: Agent 1's merged artifact + adapter serving (above), trained only on `reference.jsonl`-compatible tasks.
4. WebShop local install (above) and model access.
5. Frontier ceiling: explicit user authorization (not configured).
6. Cost estimate to decide the smallest authorized run: 47 tasks × 3 seeds × ≤20 model calls × ≈1–3 s/call on L4 at list rates (GPU $0.000222/s + CPU/RAM per `modal_app.qwen_toolcalls`)
   ≈ up to ~$1–3 per contender including cold start; **unverified until the first real probe**. Use `--max-episodes` to cap, and the 3-variable ceiling bounds spend.

## Commands
```
uv sync && uv run pytest -q                         # 340+ offline tests
uv run python -m scripts.build_eval_taskset --env-file <.env> --seed 20261110 --size 80 --held-out Sports_and_Outdoors --out-dir docs/evaluations/taskset-20261110
uv run python -m scripts.audit_split_leakage --protected docs/evaluations/taskset-20261110/protected.jsonl --reference docs/evaluations/taskset-20261110/reference.jsonl \
    --allow-not-run memory_eligibility --allow-not-run training_source_leakage            # + --training-manifest / --memory-traces once they exist
uv run python -m scripts.run_evaluation plan --evaluation-id eval-20261110-base --taskset docs/evaluations/taskset-20261110 --seeds 20261201,20261202,20261203 \
    [--memory-pool pool.jsonl] [--adapter-ref adapter_ref.json]
# after the Modal variables are set:
uv run python -m scripts.run_evaluation run --evaluation-id eval-20261110-base --env-file <.env> [--max-episodes 12]   # re-run to resume; exit 3 = blocked
export WEBSHOP_HOME=... WEBSHOP_PYTHON=...; uv run python -m scripts.run_evaluation webshop --evaluation-id eval-20261110-base --webshop-sessions 0-49
uv run python -m scripts.run_evaluation report  --evaluation-id eval-20261110-base --out-dir docs/evaluations/eval-20261110-base
uv run python -m scripts.run_evaluation publish --evaluation-id eval-20261110-base --env-file <.env> [--publish]       # dry run by default
```
Planned (not run) artifacts: `docs/evaluations/eval-20261110-base/` (manifest, WebShop blocked record, STATUS.md).
Working store `checkpoints/evaluations/` is git-ignored; reports go to `docs/evaluations/<id>/`.

## Not done / follow-ups
- Phase 2 (merge Agent 1, real base / base+memory / fine-tuned run, publish, WebShop run): not started, blocked as above.
- Review-trap tasks use the keyword-based `taskgen-v1` signals (automated-verified, not human-sampled); 4 of 47 protected tasks.
- Variance is across 3 planned seeds only; no significance test is claimed. `paired_vs_base` gives win/loss counts for a later test.
- `ModalQwenClient` serves one `checkpoint_label` and rejects others (`checkpoint_mismatch`); adapter serving is Agent 1's.
