"""Items 11-12: run ONE scripted episode on the real Elastic snapshot, persist it to Elastic and retrieve it back.
  uv run python -m scripts.live_episode --env-file .env [--keep]
Uses MockPayments (no PayPal call) and a throw-away `it_` index prefix, dropped afterwards unless --keep."""
import argparse
import json
import os
import sys
from pathlib import Path

from agents.executor import InMemoryToolExecutor
from agents.memory import RetrievalRequest
from agents.runner import run_episode
from catalog.providers.elastic import Elastic, endpoint_from_cloud_id
from memory.adapter import episode_fitness, to_trace_record
from memory.elastic import ElasticTraceRepository
from memory.provider import TraceMemoryProvider
from modal_app.scripted_shopper import ScriptUnavailable, scripted_policy
from payments.guards import GuardedPayments
from payments.mock import MockPayments
from scripts.generate_tasks import training_catalog
from tasks.schemas import TaskSpec, TaskSplit


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file")
    ap.add_argument("--tasks", default="data/tasks/tasks_v1.json")
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args()
    cat = training_catalog(a.env_file)
    doc = json.loads(Path(a.tasks).read_text())
    tasks = [TaskSpec.model_validate(t) for t in doc["tasks"]]
    task = episode = None
    for t in (x for x in tasks if x.split is TaskSplit.TRAIN and not x.is_impossible):
        try:
            policy = scripted_policy(t, cat, "agent-scripted")
        except ScriptUnavailable as e:
            print("skip", t.id, e, file=sys.stderr)
            continue
        guarded = GuardedPayments(MockPayments(auto_approve=True), cat)
        ex = InMemoryToolExecutor(cat, guarded, task_id=t.id, agent_id="agent-scripted", budget_cap=t.hard_constraints.max_total)
        episode = run_episode(episode_id=f"live-{t.id}", task=t, agent_id="agent-scripted", generation_id="gen-live-0",
                              policy=policy, executor=ex, seed=11)
        task = t
        break
    assert episode is not None, "no task could be scripted from the real snapshot"
    pick = cat.get_product(episode.recommended_products[0]) if episode.recommended_products else None
    summary = {"task_id": task.id, "split": task.split.value, "category": task.hard_constraints.category,
               "cap": str(task.hard_constraints.max_total), "termination": str(episode.termination), "killed": episode.killed,
               "kills": [k["rule_id"] for k in episode.kill_information], "fitness": episode_fitness(episode),
               "calls": [c.action.type for c in episode.tool_calls],
               "pick": {"id": pick.id, "title": pick.title[:70], "price": str(pick.price), "source": pick.source,
                        "as_of": pick.as_of.date().isoformat()} if pick else None,
               "cited_review_ids": [r for c in episode.tool_calls if c.action.type == "summarize_review_evidence" for r in c.result_references]}
    print(json.dumps({"episode": summary}, indent=1))

    # persist to a disposable prefix, then retrieve through the MemoryProvider contract
    if a.env_file:
        from scripts._env import load
        load(a.env_file, {"ELASTIC_API_KEY", "ELASTIC_ENDPOINT", "ELASTIC_CLOUD_ID"})
    es = Elastic(os.environ.get("ELASTIC_ENDPOINT") or endpoint_from_cloud_id(os.environ["ELASTIC_CLOUD_ID"]), prefix="it_")
    es.ensure_indices()
    try:
        mem = TraceMemoryProvider(ElasticTraceRepository(es), catalog_snapshot_id=task.catalog_snapshot_id,
                                  catalog_manifest_hash=task.catalog_manifest_hash)
        mem.repo.add(to_trace_record(episode, task, provenance={"payments": "mock", "policy": "scripted-oracle (not a model)"}))
        # decoys that retrieval must never return: same episode re-labelled as a test-split trace and as a killed trace
        mem.repo.add(to_trace_record(episode.model_copy(update={"episode_id": "decoy-test"}), task.model_copy(update={"split": TaskSplit.TEST})))
        mem.repo.add(to_trace_record(episode.model_copy(update={"episode_id": "decoy-killed", "killed": True,
                                     "kill_information": ({"rule_id": "K003_BUDGET_VIOLATION"},)}), task))
        mem.repo.es.call("POST", f"/{es.ix('traces')}/_refresh")
        req = RetrievalRequest("another-task", TaskSplit.TRAIN, task.hard_constraints.category, task.raw_message, 3, 0.0)
        got = mem.retrieve(req)
        test_req = mem.retrieve(RetrievalRequest("t", TaskSplit.TEST, task.hard_constraints.category, task.raw_message, 3, 0.0))
        total = es.call("POST", f"/{es.ix('traces')}/_count", {"query": {"match_all": {}}})["count"]
        print(json.dumps({"persisted_docs": total, "retrieved_ids": [e.episode_id for e in got],
                          "round_trip_equal": got[0] == episode if got else None, "test_split_request_returns": len(test_req)}, indent=1))
        assert [e.episode_id for e in got] == [episode.episode_id] and got[0] == episode and test_req == ()
    finally:
        if not a.keep:
            for n in ("products", "reviews", "traces", "kill_rules", "generations"):
                try:
                    es.call("DELETE", f"/{es.ix(n)}")
                except Exception:
                    pass


if __name__ == "__main__":
    main()
