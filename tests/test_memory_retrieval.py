from memory import InMemoryTraceRepository, TraceRecord
from memory.elastic import ElasticTraceRepository, similar_query


def tr(i, split="train", killed=False, fitness=0.9, text="running shoes under 100 dollars"):
    return TraceRecord(episode_id=i, task_id=i, agent_id="a", split=split, task_text=text, killed=killed, fitness=fitness)


def repo():
    r = InMemoryTraceRepository()
    for t in (tr("ok"), tr("test", split="test"), tr("dead", killed=True), tr("weak", fitness=0.1), tr("val", split="val", text="hiking boots")):
        r.add(t)
    return r


def test_test_split_never_retrieved():
    assert "test" not in {t.episode_id for t in repo().similar("running shoes", k=10)}


def test_killed_and_low_fitness_excluded():
    got = {t.episode_id for t in repo().similar("running shoes", k=10, min_fitness=0.5)}
    assert got == {"ok", "val"}


def test_most_similar_first_and_k_respected():
    got = repo().similar("running shoes under 100", k=1, min_fitness=0.5)
    assert [t.episode_id for t in got] == ["ok"]


def test_held_out_category_traces_are_also_never_retrieved():
    r = InMemoryTraceRepository()
    r.add(tr("ho", split="held_out_category"))
    assert r.similar("running shoes", k=5) == []


def test_add_is_idempotent_per_episode():
    r = InMemoryTraceRepository()
    r.add(tr("x")); r.add(tr("x", fitness=0.95))
    assert len(r.traces) == 1 and r.traces[0].fitness == 0.95


def test_elastic_query_carries_leakage_filter():
    f = similar_query([0.1], 3, 0.5)["knn"]["filter"]["bool"]
    assert {"terms": {"split": ["held_out_category", "test"]}} in f["must_not"]
    assert {"term": {"killed": False}} in f["filter"] and {"range": {"fitness": {"gte": 0.5}}} in f["filter"]


def test_elastic_repo_sends_filtered_knn_without_importing_elastic_in_callers():
    sent = []

    class FakeEs:
        def ix(self, n): return n
        def call(self, m, p, body=None, **k):
            sent.append((p, body)); return {"hits": {"hits": [{"_source": tr("ok").model_dump()}]}}
    got = ElasticTraceRepository(FakeEs(), embed=lambda t, kind="ingest": [0.0]).similar("shoes", k=2)
    assert got[0].episode_id == "ok" and sent[0][0] == "/traces/_search" and "must_not" in str(sent[0][1])
