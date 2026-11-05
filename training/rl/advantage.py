"""Episode rewards and group-relative advantages (GRPO). Pure functions: Decimal in, float out.

reward(episode)  = fitness, or `floor` if the episode was killed or never scored (a failure, kept as data);
advantage(i)     = (r_i - mean(group)) / (std(group) + eps), population std. A group whose rewards are all equal
                   carries no comparison and gets 0 for every member (counted by the shard builder)."""
from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from scoring.step_credit import turn_penalty
from training.planning import StepCreditWeights
from training.rollouts import RolloutRecord

EPS = Decimal("1e-6")


def episode_reward(rollout: RolloutRecord, *, floor: Decimal) -> Decimal:
    return floor if rollout.killed or rollout.fitness is None else rollout.fitness


def group_advantages(rewards: Sequence[Decimal], *, eps: Decimal = EPS) -> tuple[float, ...]:
    if len(rewards) < 2:
        raise ValueError("a GRPO group needs at least 2 samples")
    mean = sum(rewards, Decimal(0)) / len(rewards)
    var = sum(((r - mean) ** 2 for r in rewards), Decimal(0)) / len(rewards)
    if var == 0:
        return tuple(0.0 for _ in rewards)
    std = var.sqrt()
    return tuple(float((r - mean) / (std + eps)) for r in rewards)


def turn_advantages(group: Sequence[RolloutRecord], *, floor: Decimal,
                    weights: StepCreditWeights) -> tuple[tuple[float, ...], ...]:
    """Per rollout, per turn: A_i - penalty(turn) (scoring.step_credit). Order follows `group`."""
    episode = group_advantages([episode_reward(r, floor=floor) for r in group])
    return tuple(tuple(a - float(turn_penalty(t, weights)) for t in r.turns) for a, r in zip(episode, group))
