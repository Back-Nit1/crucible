"""Reproducible contender evaluation over identical task/seed pairs. Mock payments only; resumable; never invents a number.

  uv run python -m scripts.run_evaluation plan    --taskset docs/evaluations/taskset-X --seeds 1,2,3 [--memory-pool pool.jsonl] [--adapter-ref adapter_ref.json]
  uv run python -m scripts.run_evaluation run     --evaluation-id ID --env-file <.env> [--max-workers 2] [--max-episodes N]   # re-run to resume
  uv run python -m scripts.run_evaluation webshop --evaluation-id ID --webshop-sessions 0-49                                   # needs WEBSHOP_HOME/PYTHON
  uv run python -m scripts.run_evaluation report  --evaluation-id ID --out-dir docs/evaluations/ID
  uv run python -m scripts.run_evaluation publish --evaluation-id ID --env-file <.env> [--publish]                              # dry run unless --publish

`run` needs the Modal launch authorization (agents.qwen_client) and exits 3, calling nothing, without it. A fine-tuned
contender exists only when --adapter-ref points at a real, hash-valid adapter reference."""
import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

from scripts._env import load

ELASTIC = {"ELASTIC_API_KEY", "ELASTIC_ENDPOINT", "ELASTIC_CLOUD_ID"}
BLOCKED = 3


def _paths(a):
    from eval.runner import EvaluationStore
    return EvaluationStore(a.root, a.evaluation_id)


def _load_manifest(a):
    manifest = _paths(a).load_manifest()
    if manifest is None:
        raise SystemExit(f"no manifest for {a.evaluation_id} under {a.root}: run `plan` first")
    return manifest


def cmd_plan(a) -> int:
    from agents.prompts import PROMPT_VERSION
    from catalog.providers.elastic import load_manifest_hashes
    from eval.contenders import AdapterReference, load_adapter_reference, standard_contenders
    from eval.leakage import audit
    from eval.manifest import Versions, build_manifest
    from eval.memory import pool_hash
    from eval.taskset import load_tasks
    from memory import TraceRecord
    from modal_app.qwen_toolcalls import MODEL_ID, MODEL_REVISION
    from world.runtime import RULES_VERSION
    from world.taskgen import TASK_VERSION

    ts = Path(a.taskset)
    meta = json.loads((ts / "taskset.json").read_text())
    protected, reference = load_tasks(ts / "protected.jsonl", meta["protected_hash"]), load_tasks(ts / "reference.jsonl", meta["reference_hash"])
    pool = ()
    if a.memory_pool:
        pool = tuple(TraceRecord.model_validate_json(l) for l in Path(a.memory_pool).read_text().splitlines() if l.strip())
    adapter = (AdapterReference.from_artifact_manifest(a.adapter_manifest) if a.adapter_manifest else
               load_adapter_reference(a.adapter_ref) if a.adapter_ref else None)
    contenders = standard_contenders(model_id=MODEL_ID, base_revision=MODEL_REVISION, prompt_version=PROMPT_VERSION,
                                     endpoint="modal:crucible-qwen-inference/Qwen", memory_k=a.memory_k, adapter=adapter)
    if not pool:  # a memory contender over an empty pool would silently equal base
        contenders = tuple(c for c in contenders if not c.memory_enabled)
        print("note: no --memory-pool, base-qwen-memory is NOT planned", file=sys.stderr)
    manifests = load_manifest_hashes()
    report = audit(protected=protected, reference=reference, memory_traces=pool if a.memory_pool else None,
                   category_manifests=manifests, allow_not_run=frozenset({"memory_eligibility", "training_source_leakage"}))
    if not report.passed:
        print(report.to_json())
        raise SystemExit("leakage audit failed: no evaluation is planned over a leaking task set")
    manifest = build_manifest(
        evaluation_id=a.evaluation_id, tasks=protected, seeds=tuple(int(s) for s in a.seeds.split(",")), contenders=contenders,
        catalog_hash=meta["catalog_manifest_hash"], versions=Versions(prompt=PROMPT_VERSION, rules=RULES_VERSION, judge="none",
                                                                          task_generator=TASK_VERSION),
        pass_k=a.pass_k, created_at=dt.datetime.now(dt.UTC), memory_pool_hash=pool_hash(pool) if pool else None, memory_pool_size=len(pool))
    manifest = manifest.with_state(result_artifacts={"protected_tasks": str(ts / "protected.jsonl"), "protected_hash": meta["protected_hash"],
                                                      "taskset": str(ts), "memory_pool": a.memory_pool or "", "audit_hash": report.content_hash,
                                                      "adapter_manifest": a.adapter_manifest or ""})
    store = _paths(a)
    existing = store.load_manifest()
    if existing and existing.manifest_hash != manifest.manifest_hash:
        raise SystemExit(f"{a.evaluation_id} already planned with a different manifest ({existing.manifest_hash[:12]}); choose a new id")
    store.save_manifest(manifest if not existing else existing)
    (store.dir / "audit.json").write_text(report.to_json() + "\n")
    print(json.dumps({"evaluation_id": a.evaluation_id, "manifest_hash": manifest.manifest_hash, "contenders": [c.id for c in contenders],
                      "tasks": len(manifest.tasks), "seeds": list(manifest.seeds), "expected_records": manifest.expected_records,
                      "dir": str(store.dir)}, indent=1))
    return 0


def _catalog(a):
    from catalog.cache import FrozenCache
    from catalog.providers.elastic import Elastic, ElasticCatalogProvider, endpoint_from_cloud_id
    es = Elastic(os.environ.get("ELASTIC_ENDPOINT") or endpoint_from_cloud_id(os.environ["ELASTIC_CLOUD_ID"]))
    return FrozenCache(ElasticCatalogProvider(es)), es


def _client(adapter=None):
    from agents.model import InferenceError
    from agents.qwen_client import ModalQwenClient
    try:
        return ModalQwenClient.from_environment(adapter=adapter)
    except InferenceError as exc:
        print(f"BLOCKED: {exc}\nNo model call was made and no result was produced.", file=sys.stderr)
        raise SystemExit(BLOCKED)


def cmd_run(a) -> int:
    from agents.model import QwenModelAdapter
    from eval.manifest import RunStatus
    from eval.memory import FrozenEvalMemory
    from eval.runner import run_evaluation
    from eval.taskset import load_tasks
    from memory import TraceRecord
    manifest = _load_manifest(a)
    arts = manifest.result_artifacts
    tasks = {t.id: t for t in load_tasks(arts["protected_tasks"], arts["protected_hash"])}
    memory = None
    if arts.get("memory_pool"):
        pool = tuple(TraceRecord.model_validate_json(l) for l in Path(arts["memory_pool"]).read_text().splitlines() if l.strip())
        memory = FrozenEvalMemory(pool, tuple(tasks.values()))
    if a.env_file:
        load(a.env_file, ELASTIC | {"CRUCIBLE_MODAL_TOKEN_ROTATED", "CRUCIBLE_MODAL_BILLING_CONFIRMED", "CRUCIBLE_MODAL_APPROVED_CEILING_USD"})
    from training.checkpoints import selection_from_ref
    clients, adapters = {}, {}
    for contender in manifest.contenders:
        selection = (selection_from_ref(contender.adapter_ref, training_manifest_hash=contender.training_manifest_hash)
                     if contender.kind == "finetuned" else None)
        clients[contender.id] = _client(selection)
        adapters[contender.id] = QwenModelAdapter(clients[contender.id], max_retries=1)
    catalog, _ = _catalog(a)
    out = run_evaluation(manifest, tasks, catalog=catalog, model_factory=lambda c: adapters[c.id], store=_paths(a), memory=memory,
                         max_workers=a.max_workers, max_episodes=a.max_episodes, log=lambda m: print(m, file=sys.stderr))
    print(json.dumps({"status": out.status.value, "complete": out.complete, "executed": out.executed, "skipped_done": out.skipped_done,
                      "unique_records": out.unique_records, "expected": manifest.expected_records, "quarantined": out.quarantined,
                      "stopped_reason": out.stopped_reason,
                      "spent_usd_estimate": str(sum((client.spent for client in clients.values()), start=0))}, indent=1))
    return 0 if out.complete or out.status is RunStatus.INTERRUPTED else 1


def cmd_webshop(a) -> int:
    from eval.runner import atomic_write
    from eval.webshop import (EpisodeResult, ModelWebShopAgent, SubprocessWebShopEnv, blocked, check_setup, parse_sessions,
                              run_webshop)
    manifest = _load_manifest(a)
    now = dt.datetime.now(dt.UTC)
    home, python = os.environ.get("WEBSHOP_HOME"), os.environ.get("WEBSHOP_PYTHON")
    unmet = list(check_setup(home, python))
    base = _paths(a).dir / "webshop"
    results = {}
    for c in manifest.contenders:
        unmet_c = list(unmet)
        if unmet_c:
            results[c.id] = blocked(c, unmet_c, now)
            continue
        if a.env_file:
            load(a.env_file, {"CRUCIBLE_MODAL_TOKEN_ROTATED", "CRUCIBLE_MODAL_BILLING_CONFIRMED", "CRUCIBLE_MODAL_APPROVED_CEILING_USD"})
        env = SubprocessWebShopEnv(home, python)
        try:
            done = {}
            for p in (base / c.id / "episodes").glob("*.json") if (base / c.id / "episodes").is_dir() else ():
                e = EpisodeResult.model_validate_json(p.read_text())
                done[(e.session, e.seed)] = e
            from training.checkpoints import selection_from_ref
            selection = (selection_from_ref(c.adapter_ref, training_manifest_hash=c.training_manifest_hash)
                         if c.kind == "finetuned" else None)
            results[c.id] = run_webshop(c, ModelWebShopAgent(_client(selection), c), env,
                                        sessions=parse_sessions(a.webshop_sessions), seeds=manifest.seeds,
                                        now=now, raw_dir=base / c.id / "raw", done=done)
        finally:
            env.close()
    for cid, r in results.items():
        atomic_write(base / cid / "result.json", r.model_dump_json(indent=2) + "\n")
    print(json.dumps({cid: r.status for cid, r in results.items()}, indent=1))
    return 0 if all(r.status == "measured" for r in results.values()) else BLOCKED


def cmd_report(a) -> int:
    from eval.leakage import AuditReport
    from eval.report import write_report, build_report
    from eval.runner import finalize
    from eval.taskset import load_tasks
    from eval.webshop import WebShopResult
    manifest = _load_manifest(a)
    store = _paths(a)
    finalize(manifest, store)                                         # raises Incomplete unless expected == unique
    arts = manifest.result_artifacts
    tasks = {t.id: t for t in load_tasks(arts["protected_tasks"], arts["protected_hash"])}
    ws = {}
    for c in manifest.contenders:
        p = store.dir / "webshop" / c.id / "result.json"
        if p.is_file():
            ws[c.id] = WebShopResult.model_validate_json(p.read_text())
    excl = json.loads((Path(arts["taskset"]) / "exclusions.json").read_text())
    audit_report = AuditReport.model_validate_json((store.dir / "audit.json").read_text())
    report = build_report(manifest, store, tasks, audit=audit_report, exclusions=excl, webshop=ws, allow_test_double=a.allow_test_double)
    j, m = write_report(report, a.out_dir or store.dir, "report")
    print(json.dumps({"json": str(j), "markdown": str(m), "evidence_class": report["evidence_class"]}, indent=1))
    return 0


def cmd_publish(a) -> int:
    from eval.publish import measured_docs, publish
    report = json.loads((Path(a.out_dir or _paths(a).dir) / "report.json").read_text())
    docs = measured_docs(report, adapter_verified=a.adapter_verified)
    if not a.publish:
        print(json.dumps({"dry_run": True, "would_publish": [i for i, _ in docs]}, indent=1))
        return 0
    if a.env_file:
        load(a.env_file, ELASTIC)
    _, es = _catalog(a)
    print(json.dumps({"published": publish(es, "evaluations", docs), "ids": [i for i, _ in docs]}, indent=1))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in (("plan", cmd_plan), ("run", cmd_run), ("webshop", cmd_webshop), ("report", cmd_report), ("publish", cmd_publish)):
        p = sub.add_parser(name)
        p.set_defaults(fn=fn)
        p.add_argument("--evaluation-id", required=True)
        p.add_argument("--root", default="checkpoints/evaluations", help="working store (git-ignored)")
        p.add_argument("--env-file")
    sub.choices["plan"].add_argument("--taskset", required=True)
    sub.choices["plan"].add_argument("--seeds", default="20261201,20261202,20261203")
    sub.choices["plan"].add_argument("--pass-k", type=int, default=1)
    sub.choices["plan"].add_argument("--memory-k", type=int, default=2)
    sub.choices["plan"].add_argument("--memory-pool")
    adapter = sub.choices["plan"].add_mutually_exclusive_group()
    adapter.add_argument("--adapter-ref")
    adapter.add_argument("--adapter-manifest")
    sub.choices["run"].add_argument("--max-workers", type=int, default=1)
    sub.choices["run"].add_argument("--max-episodes", type=int)
    sub.choices["webshop"].add_argument("--webshop-sessions", default="0-49")
    sub.choices["report"].add_argument("--out-dir")
    sub.choices["report"].add_argument("--allow-test-double", action="store_true")
    sub.choices["publish"].add_argument("--out-dir")
    sub.choices["publish"].add_argument("--publish", action="store_true", help="write to Elastic (default: dry run)")
    sub.choices["publish"].add_argument("--adapter-verified", action="store_true")
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
