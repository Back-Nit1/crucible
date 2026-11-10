"""Observatory API: generation picker (published + unpublished), cached crowd bundle, live SSE, live training feed."""
import datetime as dt

from fastapi.testclient import TestClient

import api.observatory as obs
from api.main import create_app
from api.readers import InMemoryReader
from catalog.router import ProviderRouter
from payments.mock import MockPayments
from tests.test_api_endpoints import CFG, Snap
from tests.test_api_world import GEN, traces
from training.live import publisher, read_runs


def make(reader, source=lambda: []):
    import api.main
    original, api.main.source_from_env = api.main.source_from_env, lambda: source
    try:
        app = create_app(ProviderRouter({"elastic_snapshot": Snap()}, CFG), MockPayments(), reader=reader)
    finally:
        api.main.source_from_env = original
    return TestClient(app, raise_server_exceptions=False)


def unpublished():
    return [t.model_copy(update={"generation_id": "g2", "episode_id": t.episode_id + "-g2"}) for t in traces()]


def test_picker_lists_published_and_unpublished():
    c = make(InMemoryReader(traces() + unpublished(), [GEN]))
    rows = c.get("/observatory/generations").json()
    assert [(r["generation_id"], r["status"], r["published"], r["episodes"]) for r in rows] == [
        ("g2", "unpublished", False, 3), ("g1", "completed", True, 3)]


def test_bundle_has_one_crowd_episode_per_agent_and_caches_completed():
    reader = InMemoryReader(traces(), [GEN])
    c = make(reader)
    r = c.get("/observatory/g1?agents=30")
    assert r.status_code == 200 and r.headers["cache-control"] == "public, max-age=3600"
    body = r.json()
    assert sorted(x["agent_id"] for x in body["crowd"]) == ["agent-1", "agent-2", "agent-3"]
    assert body["crowd"][0]["steps"] and "arguments" not in body["crowd"][0]["steps"][0]  # compact: no tool args
    assert body["focus"]["replay"] and body["generation"]["generation_id"] == "g1"
    reader._traces.clear()  # a completed generation is served from cache
    assert c.get("/observatory/g1?agents=30").status_code == 200


def test_unpublished_bundle_and_missing():
    c = make(InMemoryReader(unpublished(), []))
    body = c.get("/observatory/g2?agents=2").json()
    assert body["generation"]["status"] == "unpublished" and len(body["crowd"]) == 2
    assert c.get("/observatory/g2?agents=2").headers["cache-control"] == "no-cache"
    assert c.get("/observatory/nope").status_code == 404
    assert c.get("/observatory/g2?agents=0").status_code == 422


def test_pick_crowd_round_robins_agents():
    ts = traces() + [t.model_copy(update={"episode_id": t.episode_id + "b"}) for t in traces()]
    assert [t.agent_id for t in obs.pick_crowd(ts, 4)] == ["agent-1", "agent-2", "agent-3", "agent-1"]


def test_live_stream_emits_status_training_and_new_episodes(monkeypatch):
    monkeypatch.setattr(obs, "POLL_SECONDS", 0.01)
    monkeypatch.setattr(obs, "STREAM_SECONDS", 0.2)
    reader = InMemoryReader(traces()[:1], [GEN])
    later = traces()[1:]
    calls = {"n": 0}

    def source():
        calls["n"] += 1
        if calls["n"] == 2:  # a new episode lands while the stream is open
            reader._traces.extend(later)
        return [{"run_id": "r1", "step": 3, "total_steps": 10}]
    c = make(reader, source)
    with c.stream("GET", "/observatory/g1/live") as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        text = "".join(r.iter_text())
    assert "event: status" in text and "event: training" in text and '"run_id": "r1"' in text
    assert text.count("event: episode") == 2 and "agent-3" in text


def test_training_publisher_throttles_and_whitelists():
    store, t = {}, [0.0]
    now = dt.datetime(2026, 11, 9, tzinfo=dt.UTC)
    pub = publisher(store, run_id="r1", static={"algorithm": "grpo", "base_model": "Qwen/Qwen2.5-3B-Instruct", "gpu": "L4",
                                                 "secret": "x"}, monotonic=lambda: t[0], now=lambda: now)
    pub(step=1, total_steps=10, loss=2.0)
    t[0] = 0.5
    pub(step=2, total_steps=10, loss=1.5)  # throttled
    assert store["r1"]["step"] == 1 and "secret" not in store["r1"]
    pub(step=2, total_steps=10, status="paused")  # status change always writes
    assert store["r1"]["status"] == "paused" and store["r1"]["losses"] == [2.0, 1.5]
    assert read_runs(store)[0]["base_model"] == "Qwen/Qwen2.5-3B-Instruct"


def test_training_publisher_never_raises():
    class Broken(dict):
        def __setitem__(self, k, v):
            raise RuntimeError("modal down")
    publisher(Broken(), run_id="r", static={})(step=1, total_steps=2, loss=1.0)


def _stage(root, it, stage, **body):
    d = root / it / "stages"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{stage}.json").write_text(__import__("json").dumps({"stage": stage, **body}))


def test_rounds_from_summary_and_from_live_traces(tmp_path, monkeypatch):
    import json
    monkeypatch.setenv("CRUCIBLE_LOOP_ROOT", str(tmp_path))
    # it-1 finished its world run: metrics come from summary.json
    _stage(tmp_path, "it-1", "generate", status="done", evidence="model_rollouts")
    _stage(tmp_path, "it-1", "train", status="done", checkpoint_id="sft-abc")
    out = tmp_path / "it-1" / "generation" / "it-1-gen"
    out.mkdir(parents=True)
    out.joinpath("summary.json").write_text(json.dumps({
        "policy": "model:qwen:base:p1", "fitness": {"mean": "0.5"},
        "episodes": {"completed": 10, "by_termination": {"success": 6}}, "kills": {"episodes_killed": 2}}))
    # it-2 is still generating: metrics come from its traces in the store
    _stage(tmp_path, "it-2", "generate", status="paused")
    live = [t.model_copy(update={"generation_id": "it-2-gen", "episode_id": f"{t.episode_id}-it2"}) for t in traces()]
    c = make(InMemoryReader(live, []))
    r1, r2 = c.get("/observatory/rounds").json()
    assert (r1["iteration_id"], r1["mean_fitness"], r1["kill_rate"], r1["success_rate"], r1["metrics_source"]) == (
        "it-1", 0.5, 0.2, 0.6, "summary")
    assert r1["produced_checkpoint"] == "sft-abc" and r1["next_stage"] == "curate" and r1["policy"] == "model:qwen:base:p1"
    assert (r2["generation_id"], r2["episodes"], r2["metrics_source"], r2["next_stage"]) == ("it-2-gen", 3, "traces", "generate")


def test_rounds_sort_naturally_and_empty_root(tmp_path, monkeypatch):
    monkeypatch.setenv("CRUCIBLE_LOOP_ROOT", str(tmp_path))
    c = make(InMemoryReader([], []))
    assert c.get("/observatory/rounds").json() == []
    for it in ("it-10", "it-2"):
        _stage(tmp_path, it, "generate", status="done")
    assert [x["iteration_id"] for x in c.get("/observatory/rounds").json()] == ["it-2", "it-10"]
