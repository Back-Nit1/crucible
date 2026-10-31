from decimal import Decimal

import pytest
from pydantic import ValidationError

from tasks.schemas import Difficulty, HardConstraints, TaskSpec, TaskSplit


def task(**changes):
    values = {
        "id": "task-1",
        "catalog_snapshot_id": "snapshot-test-v1",
        "raw_message": "Need running shoes under $100 in size 12.",
        "hard_constraints": HardConstraints(
            category="running-shoes", max_total=Decimal("100.00"), required_variant="12"
        ),
        "feasible_set": ("shoe-a", "shoe-b"),
        "best_value_reference": "shoe-a",
        "difficulty": Difficulty.EASY,
        "is_impossible": False,
        "split": TaskSplit.TEST,
    }
    values.update(changes)
    return TaskSpec(**values)


def test_task_contract_is_strict_and_immutable():
    spec = task()
    with pytest.raises(ValidationError):
        TaskSpec(**{**spec.model_dump(), "unexpected": True})
    with pytest.raises(ValidationError):
        spec.id = "changed"


def test_feasibility_references_are_internally_consistent():
    with pytest.raises(ValidationError, match="best_value_reference"):
        task(best_value_reference="ghost")
    with pytest.raises(ValidationError, match="is_impossible"):
        task(feasible_set=(), best_value_reference=None)


def test_impossible_task_requires_a_closest_real_product():
    impossible = task(
        feasible_set=(),
        best_value_reference=None,
        is_impossible=True,
        closest_product_id="shoe-a",
    )
    assert impossible.closest_product_id == "shoe-a"

    with pytest.raises(ValidationError, match="closest real product"):
        task(feasible_set=(), best_value_reference=None, is_impossible=True)
