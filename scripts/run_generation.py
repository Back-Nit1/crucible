"""Run (or resume) one scripted generation over the real frozen snapshot. Mock payments only.

  uv run python -m scripts.run_generation --env-file <.env> --provider elastic_snapshot --model scripted \\
      --payments mock --seed 20261101 --population 8 --tasks 12
  ... --interrupt-after 20      # stop after 20 episodes (status=interrupted); rerun the same command to resume
  ... --traces memory --checkpoint-dir /tmp/x   # offline trace store (no Elastic writes)

Outputs: <out-dir>/<generation-id>/{summary.json,summary.md,sft.jsonl,training_manifest.json}; checkpoint in
<checkpoint-dir>/gen-<id>.json. Same arguments => same tasks, population, ids and summary."""
import argparse
import json
import os
import sys
from pathlib import Path

from scripts._env import load

KEYS = {"ELASTIC_API_KEY", "ELASTIC_ENDPOINT", "ELASTIC_CLOUD_ID"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env-file")
    ap.add_argument("--provider", default="elastic_snapshot", choices=["elastic_snapshot"])
    ap.add_argument("--model", default="scripted", choices=["scripted"])
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
    if a.traces == "elastic" or os.environ.get("ELASTIC_API_KEY"):
        from catalog.providers._http import request_json

        def counting(*args, **kw):
            calls["elastic"] += 1
            return request_json(*args, **kw)
        es = Elastic(os.environ.get("ELASTIC_ENDPOINT") or endpoint_from_cloud_id(os.environ["ELASTIC_CLOUD_ID"]), transport=counting)
    catalog = FrozenCache(ElasticCatalogProvider(es))
    manifests = load_manifest_hashes()
    traces = ElasticTraceRepository(es) if a.traces == "elastic" else InMemoryTraceRepository()
    if a.traces == "elastic":
        es.update_traces_mapping()  # additive + idempotent
    tasks = generate_tasks(catalog, manifests, seed=a.seed, count=a.tasks)
    genomes = build_population(a.population, a.seed, fixtures=not a.no_fixtures)
    store = GenerationStore(FileBlobStore(a.checkpoint_dir))
    res = run_generation(generation_id=gen, seed=a.seed, genomes=genomes, tasks=tasks, manifests=manifests, catalog=catalog,
                         store=store, traces=traces, max_episodes=a.interrupt_after, log=lambda m: print(m, file=sys.stderr))
    if not res.complete:
        print(json.dumps({"generation_id": gen, "status": res.state.status.value, "executed": len(res.executed),
                          "remaining": len(res.state.remaining())}))
        return 0
    episodes, proposals, curated, next_pop = audit_and_curate(
        result=res, tasks=tasks, genomes=genomes, traces=traces, catalog=catalog, manifests=manifests, breed_seed=a.seed)
    summary = report.summarize(result=res, tasks=tasks, episodes=episodes, proposals=proposals, curated=curated, next_pop=next_pop,
                               params={"seed": a.seed, "population": a.population, "tasks": a.tasks, "model": a.model,
                                       "payments": a.payments, "provider": a.provider, "fixtures": not a.no_fixtures})
    out = Path(a.out_dir) / gen
    report.write(summary, out)
    (out / "sft.jsonl").write_text("".join(r.model_dump_json() + "\n" for r in curated.records))
    (out / "training_manifest.json").write_text(curated.manifest.model_dump_json(indent=2) + "\n")
    print(json.dumps({"generation_id": gen, "status": summary["status"], "executed_this_run": len(res.executed),
                      "episodes": summary["episodes"], "kills": summary["kills"]["by_rule"], "survivors": len(summary["survivors"]),
                      "safety": summary["safety"], "sft_records": len(curated.records), "elastic_calls": calls["elastic"],
                      "out": str(out)}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
