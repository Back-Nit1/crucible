"""Audit protected-split leakage for a task set (+ optional memory pool and training manifests). Exit 1 on any failure.

  uv run python -m scripts.audit_split_leakage --protected docs/evaluations/taskset-X/protected.jsonl \\
      --reference docs/evaluations/taskset-X/reference.jsonl --training-manifest docs/runs/gen/training_manifest.json \\
      --memory-traces traces.jsonl --out audit.json
A check with no input is reported not_run and fails the audit unless named in --allow-not-run."""
import argparse
import json
import sys
from pathlib import Path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--protected", required=True)
    ap.add_argument("--reference", required=True)
    ap.add_argument("--training-manifest", action="append")
    ap.add_argument("--memory-traces", help="JSONL of TraceRecord documents the memory pool would serve")
    ap.add_argument("--manifest-dir", help="category manifests (default: data/manifests)")
    ap.add_argument("--allow-not-run", action="append", default=[])
    ap.add_argument("--out")
    a = ap.parse_args(argv)

    from catalog.providers.elastic import load_manifest_hashes
    from eval.leakage import audit
    from eval.taskset import load_tasks
    from memory import TraceRecord
    from training.curation import TrainingManifest
    traces = None
    if a.memory_traces:
        traces = tuple(TraceRecord.model_validate_json(line) for line in Path(a.memory_traces).read_text().splitlines() if line.strip())
    manifests = None if a.training_manifest is None else tuple(
        TrainingManifest.model_validate_json(Path(p).read_text()) for p in a.training_manifest)
    report = audit(protected=load_tasks(a.protected), reference=load_tasks(a.reference), memory_traces=traces,
                   training_manifests=manifests, category_manifests=load_manifest_hashes(a.manifest_dir and Path(a.manifest_dir)),
                   allow_not_run=frozenset(a.allow_not_run))
    if a.out:
        Path(a.out).write_text(report.to_json() + "\n")
    print(json.dumps({"passed": report.passed, "checks": {n: [c.status, c.violations] for n, c in report.checks.items()}}, indent=1))
    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
