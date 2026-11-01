"""Duplicate/missing-ID audit of one generation: checkpoint pairs vs stored traces (Elastic or --traces memory is N/A).

  uv run python -m scripts.audit_traces --env-file <.env> --generation-id <id> --checkpoint-dir checkpoints/generations
Exit 0 only if expected == stored == unique episode ids with no missing/unexpected ids. Prints counts only."""
import argparse
import json
import os
import sys
from collections import Counter

from scripts._env import load

KEYS = {"ELASTIC_API_KEY", "ELASTIC_ENDPOINT", "ELASTIC_CLOUD_ID"}


def audit(state, traces) -> dict:
    expected = {f"{state.checkpoint.generation_id}:{k}" for k in
                (f"{g.id}:{t}" for g in state.checkpoint.genomes for t in state.checkpoint.task_ids)}
    ids = [t.episode_id for t in traces]
    dupes = {i: n for i, n in Counter(ids).items() if n > 1}
    report = {"generation_id": state.checkpoint.generation_id, "status": state.status.value, "expected": len(expected),
              "stored": len(ids), "unique": len(set(ids)), "duplicates": len(dupes), "missing": len(expected - set(ids)),
              "unexpected": len(set(ids) - expected)}
    report["ok"] = report["expected"] == report["stored"] == report["unique"] and not (dupes or report["missing"] or report["unexpected"])
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--env-file")
    ap.add_argument("--generation-id", required=True)
    ap.add_argument("--checkpoint-dir", default="checkpoints/generations")
    a = ap.parse_args(argv)
    if a.env_file:
        load(a.env_file, KEYS)
    from catalog.providers.elastic import Elastic, endpoint_from_cloud_id
    from memory.elastic import ElasticTraceRepository
    from world.store import FileBlobStore, GenerationStore
    state = GenerationStore(FileBlobStore(a.checkpoint_dir)).load(a.generation_id)
    if state is None:
        print(json.dumps({"error": "no checkpoint for generation"}))
        return 2
    es = Elastic(os.environ.get("ELASTIC_ENDPOINT") or endpoint_from_cloud_id(os.environ["ELASTIC_CLOUD_ID"]))
    report = audit(state, ElasticTraceRepository(es).by_generation(a.generation_id))
    print(json.dumps(report))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
