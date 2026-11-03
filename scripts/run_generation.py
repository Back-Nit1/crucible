"""Run (or resume) one generation over a frozen snapshot with the scripted OR the model-backed policy. Mock payments only.
This is the single generation entry point (modal_app/world_runner.py drives the same world.runtime).

  uv run python -m scripts.run_generation --env-file <.env> --provider elastic_snapshot --model scripted \\
      --payments mock --seed 20261101 --population 8 --tasks 12
  ... --interrupt-after 20      # stop after 20 episodes (status=interrupted); rerun the same command to resume
  ... --traces memory --checkpoint-dir /tmp/x   # offline trace store (no Elastic writes)
  ... --provider synthetic --traces memory      # offline deterministic fixture (test-only synthetic products)
  ... --model qwen --memory off|on              # model-backed; needs the Modal launch authorization (agents.qwen_client)

Outputs: <out-dir>/<generation-id>/{summary.json,summary.md,sft.jsonl,training_manifest.json}; checkpoint in
<checkpoint-dir>/gen-<id>.json. Same arguments => same tasks, population, ids and summary."""
import argparse
import json
import os
import sys
from pathlib import Path

from scripts._env import load

KEYS = {"ELASTIC_API_KEY", "ELASTIC_ENDPOINT", "ELASTIC_CLOUD_ID"}


def load_audited_taskset(taskset: Path, manifests: dict[str, str], limit: int):
    """Load reference-only generation tasks after re-running the protected/reference leakage audit."""
    from eval.leakage import audit
    from eval.taskset import load_tasks

    meta = json.loads((taskset / "taskset.json").read_text())
    protected = load_tasks(taskset / "protected.jsonl", meta["protected_hash"])
    reference = load_tasks(taskset / "reference.jsonl", meta["reference_hash"])
    report = audit(
        protected=protected,
        reference=reference,
        category_manifests=manifests,
        allow_not_run=frozenset({"memory_eligibility", "training_source_leakage"}),
    )
    if not report.passed:
        failed = ", ".join(name for name, check in report.checks.items() if check.status != "pass")
        raise ValueError(f"task set failed the leakage audit: {failed}")
    if limit > len(reference):
        raise ValueError(f"task set has {len(reference)} audited reference tasks, fewer than --tasks {limit}")
    return reference[:limit], report.content_hash


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env-file")
    ap.add_argument("--provider", default="elastic_snapshot", choices=["elastic_snapshot", "synthetic"])
    ap.add_argument("--model", default="scripted", choices=["scripted", "qwen"])
    ap.add_argument("--adapter-manifest", type=Path,
                    help="sealed artifact_manifest.json; pins every genome and request to that trained adapter")
    ap.add_argument("--taskset", type=Path,
                    help="audited task-set directory; generation consumes reference.jsonl, never protected tasks")
    ap.add_argument("--memory", default="genome", choices=["genome", "on", "off"],
                    help="force memory on/off for every genome (identical-pair base vs memory runs)")
    ap.add_argument("--payments", default="mock", choices=["mock"], help="world runs never use PayPal sandbox")
    ap.add_argument("--seed", type=int, default=20261101)
    ap.add_argument("--population", type=int, default=8)
    ap.add_argument("--tasks", type=int, default=12)
    ap.add_argument("--no-fixtures", action="store_true", help="omit the deliberate fixture agents")
    ap.add_argument("--generation-id")
    ap.add_argument("--interrupt-after", type=int)
    ap.add_argument("--traces", default="elastic", choices=["elastic", "memory"])
    ap.add_argument("--checkpoint-dir", default="checkpoints/generations")
    ap.add_argument("--out-dir", default="runs")
    a = ap.parse_args(argv)
    if a.adapter_manifest and a.model != "qwen":
        ap.error("--adapter-manifest requires --model qwen")
    if a.taskset and a.provider != "elastic_snapshot":
        ap.error("--taskset requires --provider elastic_snapshot because its tasks pin the frozen catalog manifests")
    if a.env_file:
        load(a.env_file, KEYS)
    gen = a.generation_id or f"gen-{a.seed}-p{a.population}-t{a.tasks}"

    from catalog.cache import FrozenCache
    from catalog.providers.elastic import Elastic, ElasticCatalogProvider, endpoint_from_cloud_id, load_manifest_hashes
    from memory import InMemoryTraceRepository
    from memory.elastic import ElasticTraceRepository
    from world import report
    from world.runtime import audit_and_curate, build_population, run_generation
    from world.store import FileBlobStore, GenerationStore
    from world.taskgen import generate_tasks

    calls = {"elastic": 0}
    es = None
    if a.provider == "synthetic" and a.traces == "elastic":
        ap.error("--provider synthetic is offline: use --traces memory")
    if a.provider == "elastic_snapshot" and (a.traces == "elastic" or os.environ.get("ELASTIC_API_KEY")):
        from catalog.providers._http import request_json

        def counting(*args, **kw):
            calls["elastic"] += 1
            return request_json(*args, **kw)
        es = Elastic(os.environ.get("ELASTIC_ENDPOINT") or endpoint_from_cloud_id(os.environ["ELASTIC_CLOUD_ID"]), transport=counting)
    if a.provider == "synthetic":
        from tests.fixtures.frozen import HASHES, SyntheticFrozen  # test-only synthetic data, never presented as Amazon data
        catalog, manifests = SyntheticFrozen(), dict(HASHES)
    else:
        catalog = FrozenCache(ElasticCatalogProvider(es))
        manifests = load_manifest_hashes()
    traces = ElasticTraceRepository(es) if a.traces == "elastic" else InMemoryTraceRepository()
    if a.traces == "elastic":
        es.update_traces_mapping()  # additive + idempotent
    taskset_audit_hash = None
    if a.taskset:
        try:
            tasks, taskset_audit_hash = load_audited_taskset(a.taskset, manifests, a.tasks)
        except (KeyError, OSError, ValueError, json.JSONDecodeError) as exc:
            ap.error(str(exc))
    else:
        tasks = generate_tasks(catalog, manifests, seed=a.seed, count=a.tasks)
    qwen = a.model == "qwen"
    checkpoint = "qwen-base" if qwen else "scripted-v1"
    checkpoint_catalog = None
    if qwen:
        from training.checkpoints import CheckpointCatalog
        checkpoint_catalog = CheckpointCatalog.from_manifest_files([a.adapter_manifest] if a.adapter_manifest else [])
        if a.adapter_manifest:
            checkpoint = checkpoint_catalog.labels()[1]
    genomes = build_population(a.population, a.seed, fixtures=not (a.no_fixtures or qwen),
                               checkpoint=checkpoint)
    if a.memory != "genome":
        genomes = tuple(g.model_copy(update={"memory": g.memory.model_copy(update={"enabled": a.memory == "on"})}) for g in genomes)
    policy = {}
    if qwen:
        from agents.qwen_client import ModalQwenClient
        from modal_app.qwen_toolcalls import MODEL_ID, MODEL_REVISION
        from world.runtime import model_policy_factory, model_policy_id
        adapter_for = checkpoint_catalog.adapter_for(
            lambda selection: ModalQwenClient.from_environment(adapter=selection), max_retries=1)
        policy = {"policy_factory": model_policy_factory(adapter_for, generation_id=gen),
                  "policy_id": model_policy_id(MODEL_ID, checkpoint)}
    store = GenerationStore(FileBlobStore(a.checkpoint_dir))
    res = run_generation(generation_id=gen, seed=a.seed, genomes=genomes, tasks=tasks, manifests=manifests, catalog=catalog,
                         store=store, traces=traces, max_episodes=a.interrupt_after, log=lambda m: print(m, file=sys.stderr), **policy)
    if not res.complete:
        print(json.dumps({"generation_id": gen, "status": res.state.status.value, "executed": len(res.executed),
                          "remaining": len(res.state.remaining())}))
        return 0
    episodes, proposals, curated, next_pop = audit_and_curate(
        result=res, tasks=tasks, genomes=genomes, traces=traces, catalog=catalog, manifests=manifests, breed_seed=a.seed)
    summary = report.summarize(result=res, tasks=tasks, episodes=episodes, proposals=proposals, curated=curated, next_pop=next_pop,
                               params={"seed": a.seed, "population": a.population, "tasks": a.tasks, "model": a.model,
                                       "payments": a.payments, "provider": a.provider, "fixtures": not (a.no_fixtures or qwen),
                                       "memory": a.memory, "checkpoint": checkpoint,
                                       "taskset": str(a.taskset) if a.taskset else None,
                                       "taskset_audit_hash": taskset_audit_hash})
    out = Path(a.out_dir) / gen
    report.write(summary, out)
    if a.traces == "elastic":
        from world.publish import publish_generation, publish_kill_rules
        publish_generation(es, res.state, summary)
        publish_kill_rules(es, summary["kills"]["by_rule"])
        if qwen:  # measured model episodes only: scripted runs are pipeline evidence, not model evaluations
            from eval.comparison import ContenderRun
            from eval.publish import EvaluationContext, evaluation_docs, publish
            from agents.prompts import PROMPT_VERSION
            ctx = EvaluationContext(model=MODEL_ID, catalog_hash=res.state.compat.catalog_hash, prompt_version=PROMPT_VERSION,
                                    judge_version="none", seed=a.seed, created_at=episodes[-1].ended_at, base_checkpoint="qwen-base")
            run_ = ContenderRun(contender_id=gen + (":memory" if a.memory == "on" else ":base"), checkpoint=MODEL_REVISION,
                                memory_enabled=a.memory == "on", episodes=episodes)
            publish(es, "evaluations", evaluation_docs((run_,), {t.id: t for t in tasks}, ctx))
    (out / "sft.jsonl").write_text("".join(r.model_dump_json() + "\n" for r in curated.records))
    (out / "training_manifest.json").write_text(curated.manifest.model_dump_json(indent=2) + "\n")
    print(json.dumps({"generation_id": gen, "status": summary["status"], "executed_this_run": len(res.executed),
                      "episodes": summary["episodes"], "kills": summary["kills"]["by_rule"], "survivors": len(summary["survivors"]),
                      "safety": summary["safety"], "sft_records": len(curated.records), "elastic_calls": calls["elastic"],
                      "out": str(out)}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
