"""World snapshot: one compact, capped, index-consistent document per generation, built from real traces."""
from api.snapshot import build_snapshot
from tests.test_api_world import GEN, traces

CATS = ["Office_Products", "running-shoes"]


def call(t, refs=()):
    return {"sequence": 0, "action": {"type": t}, "arguments": {}, "result_references": list(refs),
            "result_summary": "", "timestamp": "2026-11-08T00:00:00Z"}


def refusal(t, eid):
    ep = {**t.episode, "termination": "no_match",
          "tool_calls": [call("parse_intent"), call("search_catalog", ["shoe-a"]), call("report_no_match")]}
    return t.model_copy(update={"episode_id": eid, "episode": ep})


def test_shape_and_indices_are_consistent():
    s = build_snapshot(GEN, traces(), CATS)
    assert s["generation_id"] == "g1" and len(s["episodes"]) == 3
    for e in s["episodes"]:
        assert e["agent"] < len(s["agents"]) and e["world"] < len(s["worlds"])
        for kind, ref in e["path"]:
            assert 0 <= kind <= 5
            if kind == 3:
                assert ref < len(s["products"])
            if kind == 2:
                assert ref < len(s["categories"])


def test_paths_start_at_spawn_and_end_where_the_episode_ended():
    ts = traces()
    s = build_snapshot(GEN, [*ts, refusal(ts[0], "ep-9")], CATS)
    by = {e["id"]: e for e in s["episodes"]}
    assert all(e["path"][0] == [0, -1] for e in s["episodes"])
    assert by["ep-0"]["termination"] == "success" and by["ep-0"]["path"][-1][0] == 4
    assert by["ep-9"]["termination"] == "no_match" and by["ep-9"]["path"][-1][0] == 5
    assert [k for k, _ in by["ep-0"]["path"]][:3] == [0, 1, 3]  # spawn, exchange, then the opened product


def test_empty_tool_calls_path_is_spawn_only():
    t = traces()[0]
    s = build_snapshot(GEN, [t.model_copy(update={"episode": {"tool_calls": []}})], CATS)
    assert s["episodes"][0]["path"] == [[0, -1]] and s["episodes"][0]["termination"] == "unknown"


def test_unknown_category_is_appended():
    s = build_snapshot(GEN, traces(), ["Office_Products"])
    assert [c["id"] for c in s["categories"]] == ["Office_Products", "running-shoes"]
    assert s["categories"][1]["name"] == "running-shoes" and s["categories"][1]["product_count"] == 2


def test_product_cap_falls_back_to_shop():
    s = build_snapshot(GEN, traces(), CATS, max_products=0)
    assert s["products"] == [] and s["limits"]["products_included"] == 0 and s["limits"]["products_total"] == 2
    assert all(k != 3 for e in s["episodes"] for k, _ in e["path"])
    assert [1, 1] not in s["episodes"][0]["path"] and [2, 1] in s["episodes"][0]["path"]


def test_episode_cap_is_deterministic():
    a = build_snapshot(GEN, traces(), CATS, max_episodes=2)
    b = build_snapshot(GEN, list(reversed(traces())), CATS, max_episodes=2)
    assert [e["id"] for e in a["episodes"]] == [e["id"] for e in b["episodes"]]
    assert a["limits"] == {**a["limits"], "sampled": True, "episodes_total": 3, "episodes_included": 2}


def test_world_facts_from_task_items_else_unknown():
    items = [{"id": "task-ep-0", "category": "running-shoes", "max_total": "100.00", "impossible": False, "review_trap": True}]
    gen = {**GEN, "summary": {**GEN["summary"], "tasks": {"items": items}}}
    w = {x["task_id"]: x for x in build_snapshot(gen, traces(), CATS)["worlds"]}
    assert w["task-ep-0"]["budget"] == "100.00" and w["task-ep-0"]["review_trap"] is True
    assert w["task-ep-1"]["budget"] is None and w["task-ep-1"]["request"]
    assert build_snapshot(GEN, traces(), CATS)["worlds"][0]["budget"] is None


def test_agents_and_scripted_flag_come_from_the_summary():
    gen = {**GEN, "summary": {**GEN["summary"], "params": {"model": "scripted"},
                              "population": [{"id": "agent-1", "variant": "v"}], "fitness": {"by_genome": {"agent-1": "0.9"}},
                              "kills": {"by_agent": {"agent-1": {"K003_BUDGET_VIOLATION": 1}}}}}
    s = build_snapshot(gen, traces(), CATS)
    a = {x["id"]: x for x in s["agents"]}
    assert s["scripted"] is True and a["agent-1"]["fitness"] == 0.9 and a["agent-1"]["survivor"] is True
    assert a["agent-1"]["kill_rules"] == ["K003_BUDGET_VIOLATION"] and "agent-3" in a  # trace agents not in population still indexed


def test_running_generation_label_comes_from_trace_checkpoints_never_defaults_to_model():
    running = {**GEN, "status": "running", "summary": {}}
    scripted = [t.model_copy(update={"genome": {**t.genome, "model_checkpoint": "scripted-v1"}}) for t in traces()]
    assert build_snapshot(running, scripted, CATS)["scripted"] is True
    assert build_snapshot(running, traces(), CATS)["scripted"] is False  # fixture traces: qwen-base checkpoint
    assert build_snapshot(running, [], CATS)["scripted"] is None  # nothing recorded yet: unknown, not "Qwen"


def test_limits_report_expected_episodes_so_untraced_skips_are_visible():
    gen = {**GEN, "summary": {**GEN["summary"], "episodes": {"expected": 5, "script_unavailable": 2}}}
    lim = build_snapshot(gen, traces(), CATS)["limits"]
    assert lim["episodes_total"] == 3 and lim["episodes_expected"] == 5 and lim["episodes_untraced"] == 2
    assert build_snapshot({**GEN, "summary": {}}, traces(), CATS)["limits"]["episodes_expected"] is None


def test_review_steps_stay_on_the_product_they_read():
    path = build_snapshot(GEN, traces(), CATS)["episodes"][0]["path"]
    assert [2, 1] not in path  # get_reviews/summarize on shoe-a keep the shopper at shoe-a, not the shop centre
