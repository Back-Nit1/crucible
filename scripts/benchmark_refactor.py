"""Offline before/after microbenchmarks. Run: python -m scripts.benchmark_refactor.

The legacy implementations are loaded from a git revision (HEAD by default).
No providers, model endpoints, or payments are called. Timing excludes tracemalloc;
peak Python allocations are measured separately and exclude fixture construction.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import statistics
import subprocess
import sys
import time
import tracemalloc
import types

from memory import InMemoryTraceRepository, TraceRecord
from tests.test_training_dataset import curated, rebuilt
from training import dataset, shard


def baseline(path, revision):
    name = "_benchmark_" + path.replace("/", "_").replace(".", "_")
    module = types.ModuleType(name)
    sys.modules[name] = module
    source = subprocess.check_output(["git", "show", f"{revision}:{path}"], text=True)
    exec(compile(source, path, "exec"), module.__dict__)
    return module


def measure(fn, repeats):
    elapsed = []
    for _ in range(repeats):
        gc.collect()
        start = time.perf_counter()
        result = fn()
        elapsed.append(time.perf_counter() - start)
        del result
    gc.collect()
    tracemalloc.start()
    result = fn()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    del result
    return {"seconds_median": round(statistics.median(elapsed), 6), "peak_mib": round(peak / 2**20, 3)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", default="HEAD")
    parser.add_argument("--records", type=int, default=2000)
    parser.add_argument("--traces", type=int, default=10000)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if min(args.records, args.traces, args.repeats) < 1:
        parser.error("counts must be positive")
    old_dataset = baseline("training/dataset.py", args.baseline)
    old_shard = baseline("training/shard.py", args.baseline)
    old_memory = baseline("memory/__init__.py", args.baseline)
    seed, manifest = curated()
    records = tuple(seed[0].model_copy(update={"source_episode_id": f"bench-{i}"}) for i in range(args.records))
    manifest = rebuilt(records, manifest)
    current = dataset.build_dataset(records, manifest)
    assert current.shard == old_dataset.build_dataset(records, manifest).shard
    kwargs = {"expected_dataset_hash": hashlib.sha256(current.shard).hexdigest(),
              "expected_manifest_hash": manifest.content_hash}
    assert vars(shard.parse_shard(current.shard, **kwargs)) == vars(old_shard.parse_shard(current.shard, **kwargs))
    traces = [TraceRecord(episode_id=str(i), task_id="t", agent_id="a", split="train", killed=False,
                          fitness=(i % 100) / 100, scored=True, task_text=f"shoes hiking comfortable size {i % 50}")
              for i in range(args.traces)]
    old_repo, repo = old_memory.InMemoryTraceRepository(), InMemoryTraceRepository()
    old_repo.traces = repo.traces = traces
    assert old_repo.similar("comfortable hiking 12") == repo.similar("comfortable hiking 12")
    cases = {
        "content_hash": (lambda: old_dataset.curation_content_hash(records), lambda: dataset.curation_content_hash(records)),
        "build_dataset": (lambda: old_dataset.build_dataset(records, manifest), lambda: dataset.build_dataset(records, manifest)),
        "parse_shard": (lambda: old_shard.parse_shard(current.shard, **kwargs), lambda: shard.parse_shard(current.shard, **kwargs)),
        "memory_top_3": (lambda: old_repo.similar("comfortable hiking 12"), lambda: repo.similar("comfortable hiking 12")),
    }
    results = {"baseline": subprocess.check_output(["git", "rev-parse", args.baseline], text=True).strip(),
               "records": args.records, "traces": args.traces, "repeats": args.repeats,
               "shard_bytes": len(current.shard), "cases": {}}
    for name, (before, after) in cases.items():
        results["cases"][name] = {"before": measure(before, args.repeats), "after": measure(after, args.repeats)}
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
