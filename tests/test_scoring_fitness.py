from decimal import Decimal

import pytest
from pydantic import ValidationError

from scoring.fitness import calculate_fitness, calculate_quality
from scoring.schemas import (
    GateResult,
    GateViolation,
    GateViolationCode,
    QualityAssessment,
    QualityMetric,
    QualityMetricName,
)


def assessment():
    return QualityAssessment(
        metrics=(
            QualityMetric(
                name=QualityMetricName.INTENT_EXTRACTION,
                value=Decimal("0.80"),
                weight=Decimal("1"),
                evidence=("deterministic fixture comparison",),
            ),
            QualityMetric(
                name=QualityMetricName.REVIEW_GROUNDING,
                value=Decimal("1.00"),
                weight=Decimal("3"),
                evidence=("all cited ids bind to the selected product",),
            ),
        )
    )


def test_quality_is_an_explicit_decimal_weighted_mean():
    assert calculate_quality(assessment()) == Decimal("0.950")


def test_fitness_applies_gate_and_efficiency_penalty():
    passed = calculate_fitness(GateResult(value=1), assessment(), Decimal("0.05"))
    assert passed.quality == Decimal("0.950")
    assert passed.fitness == Decimal("0.900")

    failed_gate = GateResult(
        value=0,
        violations=(
            GateViolation(
                code=GateViolationCode.PRODUCT_NOT_FOUND,
                product_id="ghost",
                detail="not in fixture",
            ),
        ),
    )
    failed = calculate_fitness(failed_gate, assessment(), Decimal("0.05"))
    assert failed.fitness == Decimal("-0.050")


def test_quality_contract_rejects_duplicate_metrics():
    metric = assessment().metrics[0]
    with pytest.raises(ValidationError, match="metric names must be unique"):
        QualityAssessment(metrics=(metric, metric))
