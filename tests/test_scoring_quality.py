from decimal import Decimal

from scoring.fitness import calculate_efficiency_penalty, calculate_quality
from scoring.judge import DeterministicFakeJudge, input_hash
from scoring.quality import assess_quality
from scoring.schemas import EpisodeTrace, NoMatchOutcome
from tests.fixtures.scoring import InMemoryCatalog, feasible_task, grounded_trace


def test_quality_returns_every_explicit_component():
    assessment = assess_quality(feasible_task(), grounded_trace(), InMemoryCatalog())
    assert len({metric.name for metric in assessment.metrics}) == 12
    assert Decimal(0) <= calculate_quality(assessment) <= Decimal(1)


def test_correct_impossible_no_match_receives_full_quality():
    task = feasible_task(feasible_set=(), best_value_reference=None, is_impossible=True,
                         closest_product_id="shoe-a")
    trace = EpisodeTrace(
        task_id=task.id, catalog_snapshot_id=task.catalog_snapshot_id,
        tool_calls=grounded_trace().tool_calls,
        outcome=NoMatchOutcome(reason="nothing fits", closest_product_id="shoe-a",
                               why_it_misses="over budget", assumptions=("size exact",)))
    assert calculate_quality(assess_quality(task, trace, InMemoryCatalog())) == Decimal(1)


def test_efficiency_penalty_cannot_reward_skipped_research():
    assert calculate_efficiency_penalty(2, 5, False) == Decimal("0.20")
    assert calculate_efficiency_penalty(8, 5, True) == Decimal("0.03")


def test_fake_judge_is_versioned_hashed_cached_and_fails_closed():
    payload = {"claim": "fixture"}
    key = f"judge-v1:{input_hash(payload)}"
    judge = DeterministicFakeJudge({key: {"score": "1"}})
    assert judge.evaluate("judge-v1", payload) is judge.evaluate("judge-v1", payload)
    assert judge.evaluate("judge-v2", payload).parse_failed
