import datetime as dt
from decimal import Decimal

from agents.actions import EpisodeRecord, ParseIntent, RecordedToolCall
from agents.memory import MemoryProvider, RetrievalRequest
from memory import InMemoryTraceRepository, TraceRecord
from memory.adapter import to_trace_record, trace_from_episode
from memory.provider import TraceMemoryProvider
from tasks.schemas import HardConstraints, TaskSpec, TaskSplit, Difficulty

T = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)


def episode(eid, msg="running shoes under 100", fitness="0.8", killed=False, task="t1"):
    call = RecordedToolCall(sequence=0, action=ParseIntent(raw_message=msg, category="shoes", max_total=Decimal("100.00"),
                            assumptions=("10k",)), arguments={"raw_message": msg}, result_summary="parsed", timestamp=T)
    kill = ({"rule_id": "K003", "rule_version": 1},) if killed else ()
    return EpisodeRecord(episode_id=eid, task_id=task, agent_id="a", generation_id="g0", seed=7, tool_calls=(call,),
                         final_answer="x", score_components={"fitness": fitness}, killed=killed, kill_information=kill,
                         termination="success", started_at=T, ended_at=T)


def task(split=TaskSplit.TRAIN):
    return TaskSpec(id="t1", catalog_snapshot_id="snap", raw_message="running shoes under 100",
                    hard_constraints=HardConstraints(category="shoes", max_total=Decimal("100.00")), feasible_set=("P1",), best_value_reference="P1",
                    difficulty=Difficulty.EASY, is_impossible=False, split=split, catalog_manifest_hash="h" * 64, seed=3)


def req(split=TaskSplit.TRAIN, k=3, minimum=0.0, task_id="other", query="running shoes", category="shoes"):
    return RetrievalRequest(task_id, split, category, query, k, minimum)


def provider():
    return TraceMemoryProvider(InMemoryTraceRepository(), catalog_snapshot_id="snap", catalog_manifest_hash="h" * 64)


def test_provider_satisfies_the_agent_memory_protocol():
    p: MemoryProvider = provider()
    assert callable(p.store) and callable(p.retrieve)


def test_adapter_maps_every_required_field():
    rec = to_trace_record(episode("e1"), task())
    assert (rec.split, rec.killed, rec.fitness, rec.seed, rec.catalog_manifest_hash) == ("train", False, 0.8, 7, "h" * 64)
    assert rec.calls == ["parse_intent"] and rec.provenance["task_seed"] == 3 and rec.task_text == "running shoes under 100"
    assert rec.category == "shoes" and rec.catalog_snapshot_id == "snap"
    assert EpisodeRecord.model_validate(rec.episode) == episode("e1")  # complete EpisodeRecord survives the round trip


def test_killed_episode_keeps_its_kill_reason_and_unscored_episode_has_zero_fitness():
    rec = to_trace_record(episode("e2", killed=True), task())
    assert rec.killed and rec.kill_reason == "K003" and rec.kill_rule_ids == ["K003"]
    bare = episode("e3").model_copy(update={"score_components": {}})
    assert trace_from_episode(bare, split="train", category="shoes").fitness == 0.0


def test_store_via_message_when_no_task_is_available():
    p = provider()
    p.store(episode("e1"), split=TaskSplit.TRAIN, category="shoes", fitness=0.8)
    assert p.repo.traces[0].task_text == "running shoes under 100" and p.repo.traces[0].catalog_manifest_hash == "h" * 64


def test_retrieval_never_returns_test_held_out_killed_or_low_fitness():
    p = provider()
    for eid, split, kw in [("ok", TaskSplit.TRAIN, {}), ("tst", TaskSplit.TEST, {}), ("ho", TaskSplit.HELD_OUT_CATEGORY, {}),
                           ("dead", TaskSplit.TRAIN, {"killed": True}), ("weak", TaskSplit.TRAIN, {"fitness": "0.1"})]:
        p.store(episode(eid, **kw), split=split, category="shoes", fitness=float(kw.get("fitness", 0.8)))
    assert [e.episode_id for e in p.retrieve(req(k=10, minimum=0.5))] == ["ok"]


def test_test_split_request_gets_nothing_and_k_is_respected():
    p = provider()
    for i in range(4):
        p.store(episode(f"e{i}", fitness="0.9"), split=TaskSplit.TRAIN, category="shoes", fitness=0.9)
    assert p.retrieve(req(split=TaskSplit.TEST)) == () and p.retrieve(req(k=0)) == ()
    assert len(p.retrieve(req(k=2))) == 2


def test_ordering_is_deterministic_category_then_similarity_then_fitness_then_id():
    p = provider()
    p.store(episode("b", msg="hiking boots", fitness="0.9"), split=TaskSplit.TRAIN, category="boots", fitness=0.9)
    p.store(episode("z", fitness="0.7"), split=TaskSplit.TRAIN, category="shoes", fitness=0.7)
    p.store(episode("a", fitness="0.7"), split=TaskSplit.TRAIN, category="shoes", fitness=0.7)
    p.store(episode("hi", fitness="0.95"), split=TaskSplit.TRAIN, category="shoes", fitness=0.95)
    first = [e.episode_id for e in p.retrieve(req(k=4))]
    assert first == ["hi", "a", "z", "b"] == [e.episode_id for e in p.retrieve(req(k=4))]


def test_never_returns_the_requesting_tasks_own_episode():
    p = provider()
    p.store(episode("self", task="same"), split=TaskSplit.TRAIN, category="shoes", fitness=0.8)
    assert p.retrieve(req(task_id="same")) == ()


def test_provider_drops_a_leaked_trace_even_if_the_repository_returns_it():
    class Leaky:
        def add(self, t): ...
        def search(self, text, k, min_fitness):
            leak = trace_from_episode(episode("leak"), split="test", category="shoes")
            dead = trace_from_episode(episode("dead", killed=True), split="train", category="shoes")
            return [(leak, 1.0), (dead, 0.9)]
    assert TraceMemoryProvider(Leaky()).retrieve(req()) == ()


def test_elastic_repository_persists_the_complete_record_idempotently_by_episode_id():
    import json
    from memory.elastic import ElasticTraceRepository

    sent = []

    class Es:
        def ix(self, n): return n
        def bulk(self, index, docs, **kw): sent.append((index, docs))
    rec = to_trace_record(episode("e9"), task())
    ElasticTraceRepository(Es(), embed=lambda t, kind="ingest": [0.5]).add(rec)
    index, [(doc_id, doc)] = sent[0]
    assert index == "traces" and doc_id == "e9"
    assert doc["embedding"] == [0.5] and doc["seed"] == 7 and doc["catalog_manifest_hash"] == "h" * 64
    assert doc["episode"]["tool_calls"][0]["action"]["type"] == "parse_intent"
    json.dumps(doc)  # wire-safe


def test_traces_mapping_indexes_the_filter_fields_and_keeps_episode_unindexed():
    from catalog.providers.elastic import mappings
    props = mappings()["traces"]["properties"]
    for f in ("split", "killed", "fitness", "seed", "catalog_manifest_hash", "calls", "embedding", "kill_rule_ids"):
        assert f in props
    assert props["episode"]["enabled"] is False
