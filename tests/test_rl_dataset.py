"""Rollouts -> content-addressed crucible-grpo-v1 shard: refusals, per-turn advantages, determinism, container parse."""
import datetime as dt
import json
import random
from decimal import Decimal

import pytest

from agents.model import Message, StructuredToolCall
from tests.test_rl_advantage import rollout, turn
from training.dataset import DatasetError
from training.planning import GRPOConfig
from training.rl.advantage import turn_advantages
from training.rl.dataset import GRPO_FORMAT, build_rl_dataset, rollout_set_hash
from training.shard import parse_shard

D = Decimal
NOW = dt.datetime(2026, 11, 5, tzinfo=dt.timezone.utc)
CFG = GRPOConfig()


def episode_turns(n, **last):
    """n consistent turns: turn i saw the user message plus calls/results 0..i-1 (as agents.model.render_messages does)."""
    history = [Message(role="user", content="need trail shoes under $120")]
    turns = []
    for i in range(n):
        flags = last if i == n - 1 else {}
        call = StructuredToolCall(name="search_catalog", arguments={"query": f"trail shoes {i}"})
        base = turn(i, **flags)
        turns.append(base.model_copy(update={"messages": tuple(history), "tool_call": call}))
        history += [Message(role="assistant", tool_name=call.name, tool_arguments=call.arguments),
                    Message(role="tool", tool_name=call.name, tool_result={"references": [], "summary": "ok", "error_code": None})]
    return tuple(turns)


def group(task="t-1", g="a" * 64, fitnesses=(D("0.9"), D("0.2"))):
    return [rollout(episode_id=f"{task}-s{i}", task_id=task, group=g, sample=i, fitness=f, turns=episode_turns(2 + i))
            for i, f in enumerate(fitnesses)]


def test_shard_carries_per_turn_advantages_and_parses_in_the_container():
    rollouts = group() + group("t-2", "b" * 64, (D("0.5"), D("0.5")))  # second group: zero variance, no penalties
    out = build_rl_dataset(rollouts, CFG, created_at=NOW)
    assert out.stats == {"rollouts": 4, "groups": 2, "zero_variance_groups": 1, "killed": 0, "unscored": 0,
                         "rows": 2, "dropped_no_signal": 2, "dropped_no_turns": 0}
    sh = parse_shard(out.dataset.shard, expected_dataset_hash=out.dataset.dataset_hash,
                     expected_manifest_hash=out.manifest.content_hash)
    assert sh.format == GRPO_FORMAT and sh.episode_ids == ["t-1-s0", "t-1-s1"]
    assert sh.turn_advantages == [list(a) for a in turn_advantages(group(), floor=CFG.reward_floor, weights=CFG.step_credit)]
    assert sh.example_systems == ["be careful", "be careful"]
    first = sh.examples[0]
    assert [m["role"] for m in first] == ["user", "assistant", "tool", "assistant"]  # full episode, ends on the last call
    assert sum(m["role"] == "assistant" for m in first) == len(sh.turn_advantages[0])
    assert out.dataset.record_count == 2 and out.manifest.content_hash == rollout_set_hash(rollouts)
    assert set(out.manifest.source_episode_ids) == {r.episode_id for r in rollouts}  # audit covers every rollout used


def test_shard_is_deterministic_and_order_independent():
    rollouts = group() + group("t-2", "b" * 64, (D("0.1"), D("0.7"), D("0.3")))
    a = build_rl_dataset(rollouts, CFG, created_at=NOW)
    shuffled = rollouts[:]
    random.Random(1).shuffle(shuffled)
    b = build_rl_dataset(shuffled, CFG, created_at=NOW)
    assert a.dataset.dataset_hash == b.dataset.dataset_hash and a.manifest == b.manifest


def test_killed_and_unscored_failures_are_kept_as_negative_rows():
    rollouts = [rollout(episode_id="ok", fitness=D("0.8"), turns=episode_turns(1)),
                rollout(episode_id="killed", sample=1, fitness=D("0"), killed=True, turns=episode_turns(2, kill_rules=("K001",))),
                rollout(episode_id="unscored", sample=2, fitness=None, turns=episode_turns(1))]
    out = build_rl_dataset(rollouts, CFG, created_at=NOW)
    assert out.stats["killed"] == 1 and out.stats["unscored"] == 1 and out.stats["rows"] == 3
    sh = parse_shard(out.dataset.shard, expected_dataset_hash=out.dataset.dataset_hash, expected_manifest_hash=out.manifest.content_hash)
    adv = dict(zip(sh.episode_ids, sh.turn_advantages))
    assert adv["ok"][0] > 0 and adv["killed"][-1] < adv["killed"][0] < 0 and adv["unscored"][0] < 0


@pytest.mark.parametrize("change, code", [
    (lambda rs: [rs[0].model_copy(update={"split": "test"}), *rs[1:]], "forbidden_split"),
    (lambda rs: [rs[0].model_copy(update={"split": "held_out_category"}), *rs[1:]], "forbidden_split"),
    (lambda rs: [r.model_copy(update={"scripted": True}) for r in rs], "scripted_traces"),
    (lambda rs: [rs[0].model_copy(update={"adapter_hash": "f" * 64, "model_checkpoint": "qwen-lora-ffffffffffff"}), *rs[1:]],
     "stale_rollouts"),
    (lambda rs: rs[:1], "group_too_small"),
    (lambda rs: [rs[0], rs[0]], "duplicate_episode"),
    (lambda rs: [rs[0].model_copy(update={"memory_enabled": True}), *rs[1:]], "inexact_prompt"),
    (lambda rs: [], "empty_rollouts"),
    (lambda rs: [rs[0].model_copy(update={"turns": tuple(reversed(rs[0].turns))}), *rs[1:]], "malformed_rollout"),
])
def test_refusals(change, code):
    with pytest.raises(DatasetError) as err:
        build_rl_dataset(change(group()), CFG, created_at=NOW)
    assert err.value.code == code


def test_scripted_rollouts_need_the_flag_and_are_labelled():
    rollouts = [r.model_copy(update={"scripted": True, "model_version": "scripted-v1", "system_prompt": None}) for r in group()]
    out = build_rl_dataset(rollouts, CFG, created_at=NOW, allow_scripted=True)
    assert out.manifest.model_version == "scripted-v1"
    header = json.loads(out.dataset.shard.splitlines()[0])["header"]
    assert header["source_model_version"] == "scripted-v1" and header["scripted"] is True


def test_rollouts_must_come_from_the_adapter_being_updated():
    adapter = GRPOConfig(policy_checkpoint="qwen-lora-" + "c" * 12, policy_adapter_run_id="run-prev", policy_adapter_hash="c" * 64)
    on_policy = [r.model_copy(update={"model_checkpoint": "qwen-lora-" + "c" * 12, "adapter_hash": "c" * 64}) for r in group()]
    assert build_rl_dataset(on_policy, adapter, created_at=NOW).stats["rows"] == 2
    with pytest.raises(DatasetError) as err:
        build_rl_dataset(group(), adapter, created_at=NOW)  # base rollouts cannot update the adapter
    assert err.value.code == "stale_rollouts"
