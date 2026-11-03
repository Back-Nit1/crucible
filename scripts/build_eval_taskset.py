"""Build the product-disjoint evaluation task set from the frozen snapshot, audit it, and write it.

  uv run python -m scripts.build_eval_taskset --env-file <.env> --seed 20261110 --size 80 --held-out Sports_and_Outdoors \\
      --out-dir docs/evaluations/taskset-20261110
  uv run python -m scripts.build_eval_taskset --provider synthetic --out-dir /tmp/x     # offline, test-only products

Writes protected.jsonl (evaluation: test + held-out-category), reference.jsonl (train/val: the ONLY tasks generation and
training may use), exclusions.json (text-duplicate drops, with reasons) and audit.json. Exits 1 when the audit fails."""
import argparse
import json
import os
import sys
from pathlib import Path

from scripts._env import load


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env-file")
    ap.add_argument("--provider", default="elastic_snapshot", choices=["elastic_snapshot", "synthetic"])
    ap.add_argument("--seed", type=int, default=20261110)
    ap.add_argument("--size", type=int, default=80)
    ap.add_argument("--held-out", action="append", default=[], help="category kept entirely out of train/val/memory")
    ap.add_argument("--trap-percent", type=int, default=10)
    ap.add_argument("--out-dir", required=True)
    a = ap.parse_args(argv)
    if a.env_file:
        load(a.env_file, {"ELASTIC_API_KEY", "ELASTIC_ENDPOINT", "ELASTIC_CLOUD_ID"})

    from eval.leakage import audit
    from eval.taskset import build_eval_taskset, dedupe_protected, partition, write_tasks
    if a.provider == "synthetic":
        from tests.fixtures.eval_catalog import HASHES, BigSynthetic  # test-only data, never presented as Amazon data
        catalog, manifests = BigSynthetic(), dict(HASHES)
    else:
        from catalog.cache import FrozenCache
        from catalog.providers.elastic import Elastic, ElasticCatalogProvider, endpoint_from_cloud_id, load_manifest_hashes
        es = Elastic(os.environ.get("ELASTIC_ENDPOINT") or endpoint_from_cloud_id(os.environ["ELASTIC_CLOUD_ID"]))
        catalog, manifests = FrozenCache(ElasticCatalogProvider(es)), load_manifest_hashes()
    batch = build_eval_taskset(catalog, manifests, seed=a.seed, size=a.size, held_out_categories=frozenset(a.held_out),
                               review_trap_percent=a.trap_percent)
    protected, reference = partition(batch.tasks)
    protected, excluded = dedupe_protected(protected, reference)
    # memory pool and training manifests do not exist yet: those checks are reported not_run (and re-run at `plan` time)
    report = audit(protected=protected, reference=reference, category_manifests=manifests,
                   allow_not_run=frozenset({"memory_eligibility", "training_source_leakage"}))
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    meta = {"protected_hash": write_tasks(out / "protected.jsonl", protected),
            "reference_hash": write_tasks(out / "reference.jsonl", reference),
            "batch_content_hash": batch.manifest.content_hash, "catalog_manifest_hash": batch.manifest.catalog_manifest_hash,
            "category_manifest_hashes": batch.manifest.category_manifest_hashes, "seed": a.seed, "requested_size": a.size,
            "protected": len(protected), "reference": len(reference), "excluded_duplicates": len(excluded),
            "held_out_categories": sorted(a.held_out), "provider": a.provider,
            "splits": {s: sum(t.split.value == s for t in batch.tasks) for s in ("train", "val", "test", "held_out_category")}}
    (out / "taskset.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")
    (out / "exclusions.json").write_text(json.dumps(excluded, indent=2, sort_keys=True) + "\n")
    (out / "audit.json").write_text(report.to_json() + "\n")
    print(json.dumps({**meta, "audit_passed": report.passed, "out": str(out)}, indent=1))
    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
