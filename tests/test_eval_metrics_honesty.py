"""No fabricated latency, cost, variance or score: unmeasured means excluded / null, never zero."""
from decimal import Decimal

from eval.harness import calculate_metrics
from tasks.schemas import TaskSplit
from tests.test_training_curation import successful_episode


def base(episode_id="ep-1"):
    task, ep = successful_episode(episode_id)
    return task.model_copy(update={"split": TaskSplit.TEST}), ep


def test_latency_and_cost_are_null_when_nothing_was_measured():
    task, ep = base()
    m = calculate_metrics((ep.model_copy(update={"model_metadata": ()}),), {task.id: task}, pass_k=1).metrics
    assert m["latency_ms"].value is None and m["latency_ms"].excluded == 1 and m["latency_ms"].denominator == 0
    assert m["cost_per_task"].value is None
    assert m["latency_ms"].failure_reasons == {"no_model_latency_recorded": 1}


def test_unknown_cost_is_excluded_not_counted_as_zero():
    task, ep = base()
    known = ep.model_copy(update={"model_metadata": ({"latency_ms": 100, "cost_known": True},), "cost": Decimal("0.02")})
    unknown = ep.model_copy(update={"episode_id": "ep-2", "seed": 2, "cost": Decimal("0"),
                                    "model_metadata": ({"latency_ms": 300, "cost_known": False},)})
    m = calculate_metrics((known, unknown), {task.id: task}, pass_k=1).metrics
    assert (m["cost_per_task"].numerator, m["cost_per_task"].denominator, m["cost_per_task"].excluded) == (Decimal("0.02"), 1, 1)
    assert m["latency_ms"].value == 200 and m["cost_per_task"].failure_reasons == {"cost_unknown": 1}


def test_variance_is_computed_across_real_seeds_and_absent_for_one_seed():
    task, ep = base()
    runs = []
    for seed, ok in ((1, True), (2, False), (3, True), (4, False)):
        runs.append(ep.model_copy(update={"episode_id": f"e{seed}", "seed": seed, "model_metadata": ({"latency_ms": 5},),
                                          "termination": "success" if ok else "instant_kill", "killed": not ok,
                                          "kill_information": () if ok else ({"rule_id": "K003_BUDGET_VIOLATION"},),
                                          "score_components": {**ep.score_components, "gate": 1 if ok else 0}}))
    report = calculate_metrics(tuple(runs), {task.id: task}, pass_k=1)
    assert report.seeds == (1, 2, 3, 4) and report.variance_across_seeds["success_rate"] == Decimal("0.25")
    assert report.metrics["success_rate"].failure_reasons == {"kill:K003_BUDGET_VIOLATION": 2, "termination:instant_kill": 2}
    single = calculate_metrics(tuple(runs[:1]), {task.id: task}, pass_k=1)
    assert single.variance_across_seeds["success_rate"] is None


def test_held_out_metric_has_an_empty_denominator_without_held_out_tasks():
    task, ep = base()
    m = calculate_metrics((ep,), {task.id: task}, pass_k=1).metrics["held_out_category_performance"]
    assert m.value is None and m.denominator == 0 and m.excluded == 1
