"""Per-turn credit for GRPO: which tool call broke a rule.

    penalty(turn) = w_schema * [turn.schema_valid is False]
                  + w_ungrounded * [turn.grounded is False]        (None = the call cites nothing: no penalty)
                  + w_kill * len(turn.kill_rules)                  (kill rules attributed to this turn)

The shard builder subtracts it from the episode's group-relative advantage on that turn's tokens only. Episode fitness and
the kill rules themselves are unchanged; this is RL-only shaping."""
from __future__ import annotations

from decimal import Decimal

from training.planning import StepCreditWeights
from training.rollouts import RolloutTurn

__all__ = ["StepCreditWeights", "turn_penalty"]


def turn_penalty(turn: RolloutTurn, weights: StepCreditWeights) -> Decimal:
    return (weights.invalid_schema * (not turn.schema_valid) + weights.ungrounded * (turn.grounded is False)
            + weights.kill_rule * len(turn.kill_rules))
