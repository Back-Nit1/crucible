from datetime import datetime, timezone

from decimal import Decimal

from agents.actions import (
    Compare, ConfirmAndPay, GetProduct, GetReviews, ParseIntent, ProposePurchase,
    SearchCatalog, SummarizeReviewEvidence,
)
from agents.runner import ScriptedPolicy, run_episode
from scoring.schemas import ReviewClaim, ReviewSort
from tasks.schemas import TaskSplit
from tests.test_episode_runner import NOW, make_executor
from tests.fixtures.scoring import feasible_task
from payments.guards import idempotency_key
from training.curation import curate_survivors
from tests.fixtures.scoring import InMemoryCatalog


def successful_episode(identifier="ep-train"):
    task = feasible_task(split=TaskSplit.TRAIN)
    _, executor = make_executor(task)
    actions = [
        ParseIntent(raw_message=task.raw_message, category="running-shoes", max_total=Decimal("100"), assumptions=("size 12",)),
        SearchCatalog(query="", filters={"category": "running-shoes"}), GetProduct(product_id="shoe-a"),
        GetReviews(product_id="shoe-a", focus="support", sort=ReviewSort.CRITICAL, limit=2),
        Compare(product_ids=("shoe-a", "shoe-b")),
        SummarizeReviewEvidence(product_id="shoe-a", user_context="support", claims=(ReviewClaim(
            concern="support", claim="grounded", review_ids=("review-a-positive", "review-a-critical")),)),
        ProposePurchase(product_id="shoe-a", variant="12", expected_total=Decimal("89"), assumptions=("size 12",)),
        ConfirmAndPay(pending_order_id=idempotency_key(task.id, "agent-1", "shoe-a", "12"), user_confirmed=True),
    ]
    return task, run_episode(episode_id=identifier, task=task, agent_id="agent-1", generation_id="gen",
        policy=ScriptedPolicy(actions), executor=executor, seed=1, clock=lambda: NOW)


def test_curation_excludes_evaluation_killed_invalid_and_duplicates_with_stable_manifest():
    task, episode = successful_episode()
    duplicate = episode.model_copy(update={"episode_id": "ep-z"})
    killed = episode.model_copy(update={"episode_id": "ep-dead", "killed": True,
        "kill_information": ({"rule": "fixture"},), "termination": "instant_kill"})
    test_task = task.model_copy(update={"id": "task-test", "split": TaskSplit.TEST})
    leaked = episode.model_copy(update={"episode_id": "ep-test", "task_id": "task-test"})
    created = datetime(2026, 10, 31, tzinfo=timezone.utc)
    args = ((episode, duplicate, killed, leaked), {task.id: task, test_task.id: test_task}, InMemoryCatalog())
    first = curate_survivors(*args, catalog_hash="abc", task_version="1", rule_version="1", created_at=created,
                             model_version="scripted-v1")
    second = curate_survivors(*args, catalog_hash="abc", task_version="1", rule_version="1", created_at=created,
                              model_version="scripted-v1")
    assert len(first.records) == 1 and first.manifest == second.manifest
    assert first.exclusions == {"ep-dead": "killed", "ep-test": "evaluation_leakage", "ep-z": "duplicate_trace"}
    assert first.manifest.model_version == "scripted-v1"
    assert first.manifest.source_task_splits == {"ep-train": TaskSplit.TRAIN}
    assert len(first.manifest.deduplication_hash) == 64
