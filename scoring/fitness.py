"""Pure Decimal arithmetic for Q and final episode fitness."""

from decimal import Decimal

from scoring.schemas import GateResult, QualityAssessment, ScoreResult


def calculate_quality(assessment: QualityAssessment) -> Decimal:
    """Return the explicitly weighted mean of the supplied quality metrics."""
    total_weight = sum((metric.weight for metric in assessment.metrics), start=Decimal(0))
    weighted_score = sum(
        (metric.value * metric.weight for metric in assessment.metrics), start=Decimal(0)
    )
    return weighted_score / total_weight


def calculate_fitness(
    gate: GateResult, assessment: QualityAssessment, efficiency_penalty: Decimal,
    max_efficiency_penalty: Decimal = Decimal("0.20"),
) -> ScoreResult:
    """Apply the specified formula: fitness = G * Q - efficiency penalty."""
    if efficiency_penalty < 0:
        raise ValueError("efficiency penalty cannot be negative")
    efficiency_penalty = min(efficiency_penalty, max_efficiency_penalty)
    quality = calculate_quality(assessment)
    fitness = Decimal(gate.value) * quality - efficiency_penalty
    return ScoreResult(
        gate=gate.value,
        quality=quality,
        efficiency_penalty=efficiency_penalty,
        fitness=fitness,
    )


def calculate_efficiency_penalty(
    tool_calls: int, required_calls: int, research_sufficient: bool, *,
    per_extra_call: Decimal = Decimal("0.01"), cap: Decimal = Decimal("0.20"),
) -> Decimal:
    """Missing research gets the maximum penalty; only excess valid work is otherwise charged."""
    if min(tool_calls, required_calls) < 0 or per_extra_call < 0 or cap < 0:
        raise ValueError("efficiency inputs cannot be negative")
    if not research_sufficient:
        return cap
    return min(cap, Decimal(max(0, tool_calls - required_calls)) * per_extra_call)
