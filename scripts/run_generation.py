"""Item 13: one complete generation over REAL snapshot tasks, in memory, mock payments, with a simulated interruption.
  uv run python -m scripts.run_generation --env-file .env --population 4 --tasks 10 --interrupt-after 15
Scripted policy (not a model): the numbers are pipeline evidence, not agent performance."""
import argparse
import json
import tempfile
from collections import Counter
from pathlib import Path

from memory import InMemoryTraceRepository
from memory.checkpoints import CheckpointStore
from memory.provider import TraceMemoryProvider
from modal_app.generation_runner import run_generation
from scripts.generate_tasks import training_catalog
from tasks.schemas import TaskSpec, TaskSplit
from world.evolution import initialize_population


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file")
    ap.add_argument("--tasks-file", default="data/tasks/tasks_v1.json")
    ap.add_argument("--population", type=int, default=4)
    ap.add_argument("--tasks", type=int, default=10)
    ap.add_argument("--interrupt-after", type=int, default=15)
    ap.add_argument("--seed", type=int, default=20261101)
    a = ap.parse_args()
    cat = training_catalog(a.env_file)
    doc = json.loads(Path(a.tasks_file).read_text())
    pool = [TaskSpec.model_validate(t) for t in doc["tasks"]]
    train = [t for t in pool if t.split is TaskSplit.TRAIN]
    feas = [t for t in train if not t.is_impossible][: a.tasks - 3]
    imp = [t for t in train if t.is_impossible][:3]
    tasks = feas + imp
    genomes = initialize_population(a.population, a.seed)
    mem = TraceMemoryProvider(InMemoryTraceRepository(), catalog_snapshot_id=doc["snapshot_id"], catalog_manifest_hash=doc["snapshot_id"])
    with tempfile.TemporaryDirectory() as d:
        first = run_generation(store=CheckpointStore(d), generation_id="gen-live-0", genomes=genomes, tasks=tasks, catalog=cat,
                               memory=mem, seed=a.seed, max_episodes=a.interrupt_after)
        print(json.dumps({"after_interruption": {"executed": len(first.executed), "complete": first.complete,
                          "remaining": len(CheckpointStore(d).remaining("gen-live-0"))}}))
        final = run_generation(store=CheckpointStore(d), generation_id="gen-live-0", genomes=genomes, tasks=tasks, catalog=cat,
                               memory=mem, seed=a.seed)
        traces = mem.repo.traces
        ids = [t.episode_id for t in traces]
        out = {"pairs": len(genomes) * len(tasks), "executed_first": len(first.executed), "executed_resumed": len(final.executed),
               "overlap": len(set(first.executed) & set(final.executed)), "complete": final.complete,
               "traces": len(ids), "duplicate_trace_ids": len(ids) - len(set(ids)), "skipped": len(final.skipped),
               "terminations": dict(Counter(t.termination for t in traces)), "killed_episodes": sum(t.killed for t in traces),
               "kill_rules": dict(Counter(r for t in traces for r in t.kill_rule_ids)),
               "fitness_by_genome": {g: str(round(f, 4)) for g, f in final.fitness.items()}, "killed_genomes": list(final.killed),
               "survivors": list(final.survivors), "next_generation_size": len(final.next_generation),
               "skipped_reasons": dict(Counter(final.skipped.values()))}
        print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
