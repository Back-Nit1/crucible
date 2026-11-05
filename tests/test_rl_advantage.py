"""GRPO rewards and group-relative advantages: pure Decimal-in / float-out functions."""
from decimal import Decimal

import pytest

from agents.model import Message, StructuredToolCall
from training.rl.advantage import episode_reward, group_advantages
from training.rollouts import RolloutRecord, RolloutTurn

D = Decimal


def turn(i=0, *, schema_valid=True, grounded=None, kill_rules=()):
    return RolloutTurn(index=i, messages=(Message(role="user", content="need shoes under $100"),),
                       tool_call=StructuredToolCall(name="search_catalog", arguments={"query": "shoes"}),
                       tool_result={"references": [], "summary": "ok", "error_code": None},
                       schema_valid=schema_valid, grounded=grounded, kill_rules=kill_rules)


def rollout(*, episode_id="ep-0", group="a" * 64, sample=0, fitness=D("0.5"), killed=False, turns=None, **kw):
    fields = dict(episode_id=episode_id, generation_id="g", iteration_id="it-1", task_id="t-1", split="train", group_id=group,
                  sample_index=sample, seed=sample, genome_id="gen-0", model_checkpoint="qwen-base", adapter_hash=None,
                  prompt_variant="grounded-shopper-v1", system_prompt="be careful", temperature=D("0.7"), memory_enabled=False,
                  model_version="qwen-base", scripted=False, turns=turns if turns is not None else (turn(),),
                  termination="instant_kill" if killed else "success", gate=None if fitness is None else (0 if killed else 1),
                  quality=None if fitness is None else D("0.6"), efficiency_penalty=None if fitness is None else D("0.1"),
                  fitness=fitness, killed=killed, kill_reasons=("K001",) if killed else ())
    return RolloutRecord(**{**fields, **kw})


def test_reward_is_fitness_and_killed_or_unscored_get_the_floor():
    assert episode_reward(rollout(fitness=D("0.42")), floor=D("-1")) == D("0.42")
    assert episode_reward(rollout(fitness=D("0.3"), killed=True), floor=D("-1")) == D("-1")  # killed: floor even if fitness exists
    assert episode_reward(rollout(fitness=None), floor=D("-0.5")) == D("-0.5")              # unscored failure
    assert episode_reward(rollout(fitness=D("-0.2")), floor=D("-1")) == D("-0.2")            # negative fitness kept as is


def test_group_advantage_is_standardized_against_the_group():
    adv = group_advantages([D("1"), D("0"), D("0.5"), D("-1")])
    assert all(isinstance(a, float) for a in adv)
    assert abs(sum(adv)) < 1e-9                          # zero mean
    assert adv[0] > adv[2] > adv[1] > adv[3]             # order preserved
    assert abs(sum(a * a for a in adv) / 4 - 1) < 1e-4    # unit (population) variance, up to eps
    assert group_advantages([D("1"), D("-1")]) == pytest.approx([1.0, -1.0], abs=1e-5)


def test_failures_stay_in_with_negative_advantage():
    rewards = [episode_reward(r, floor=D("-1")) for r in (rollout(fitness=D("0.8")), rollout(fitness=D("0.1"), killed=True))]
    good, killed = group_advantages(rewards)
    assert good > 0 > killed


def test_zero_variance_group_contributes_nothing():
    assert group_advantages([D("0.5")] * 3) == (0.0, 0.0, 0.0)
    assert group_advantages([D("-1"), D("-1")]) == (0.0, 0.0)  # all killed: nothing to compare


def test_group_advantage_refuses_degenerate_groups():
    with pytest.raises(ValueError):
        group_advantages([D("1")])
    with pytest.raises(ValueError):
        group_advantages([])


# --- B3: per-turn credit -------------------------------------------------------------------------------------------
from scoring.step_credit import StepCreditWeights, turn_penalty  # noqa: E402
from training.rl.advantage import turn_advantages  # noqa: E402

W = StepCreditWeights(invalid_schema=D("0.5"), ungrounded=D("0.25"), kill_rule=D("1"))


def test_turn_penalty_names_the_turn_that_broke_a_rule():
    assert turn_penalty(turn(), W) == 0
    assert turn_penalty(turn(grounded=True), W) == 0
    assert turn_penalty(turn(schema_valid=False), W) == D("0.5")
    assert turn_penalty(turn(grounded=False), W) == D("0.25")
    assert turn_penalty(turn(kill_rules=("K001", "K002")), W) == D("2")  # each attributed rule counts
    assert turn_penalty(turn(schema_valid=False, grounded=False, kill_rules=("K001",)), W) == D("1.75")


def test_turn_advantage_is_group_advantage_minus_that_turns_penalty():
    good = rollout(episode_id="a", fitness=D("0.9"), turns=(turn(0), turn(1)))
    bad = rollout(episode_id="b", sample=1, fitness=D("0.1"), killed=True,
                  turns=(turn(0), turn(1, grounded=False), turn(2, kill_rules=("K001",))))
    out = turn_advantages([good, bad], floor=D("-1"), weights=W)
    assert out[0] == pytest.approx((1.0, 1.0), abs=1e-5)
    assert out[1] == pytest.approx((-1.0, -1.25, -2.0), abs=1e-5)  # only the offending turns pay extra


def test_zero_variance_group_still_penalizes_the_offending_turn():
    a = rollout(episode_id="a", killed=True, turns=(turn(0), turn(1, kill_rules=("K001",))))
    b = rollout(episode_id="b", sample=1, killed=True, turns=(turn(0, schema_valid=False),))
    assert turn_advantages([a, b], floor=D("-1"), weights=W) == ((0.0, -1.0), (-0.5,))


def test_equal_rewards_are_zero_variance_even_when_the_decimal_mean_rounds():
    r = D(1) / D(3) + D("0.46")  # 0.79333...: the Decimal mean of copies is not exactly r
    assert group_advantages([r, r, r, r]) == (0.0, 0.0, 0.0, 0.0)
