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
    gate: GateResult, assessment: QualityAssessment, efficiency_penalty: Decimal
) -> ScoreResult:
    """Apply the specified formula: fitness = G * Q - efficiency penalty."""
    quality = calculate_quality(assessment)
    fitness = Decimal(gate.value) * quality - efficiency_penalty
    return ScoreResult(
        gate=gate.value,
        quality=quality,
        efficiency_penalty=efficiency_penalty,
        fitness=fitness,
    )
