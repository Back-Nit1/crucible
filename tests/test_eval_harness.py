from decimal import Decimal

from eval.harness import calculate_metrics
from tasks.schemas import TaskSplit
from tests.test_training_curation import successful_episode


def test_hand_computed_metrics_and_empty_denominators_render():
    task, success = successful_episode("ep-1")
    task = task.model_copy(update={"split": TaskSplit.TRAIN})
    failed = success.model_copy(update={"episode_id": "ep-2", "seed": 2,
        "termination": "instant_kill", "killed": True,
        "kill_information": ({"rule_id": "K001_HALLUCINATED_PRODUCT"},),
        "score_components": {**success.score_components, "gate": 0}})
    report = calculate_metrics((success, failed), {task.id: task}, pass_k=2)
    assert report.metrics["success_rate"].numerator == 1
    assert report.metrics["success_rate"].denominator == 2
    assert report.metrics["success_rate"].value == Decimal("0.5")
    assert report.metrics["hallucination_rate"].value == Decimal("0.5")
    assert report.metrics["correct_refusal_rate"].value is None
    assert report.metrics["pass_at_2"].value == Decimal(1)
    assert report.variance_across_seeds["success_rate"] == Decimal("0.25")
    assert '"correct_refusal_rate"' in report.to_json()
    assert "| success_rate |" in report.to_markdown()


def test_unknown_tasks_are_explicitly_excluded():
    _, episode = successful_episode("unknown")
    report = calculate_metrics((episode,), {}, pass_k=1)
    assert report.metrics["success_rate"].denominator == 0
    assert report.metrics["success_rate"].excluded == 1
