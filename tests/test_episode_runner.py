from datetime import datetime, timezone
from decimal import Decimal

from agents.actions import (
    Compare, ConfirmAndPay, GetProduct, GetReviews, ParseIntent, ProposePurchase,
    ReportNoMatch, SearchCatalog, SummarizeReviewEvidence,
)
from agents.executor import InMemoryToolExecutor
from agents.runner import ScriptedPolicy, run_episode
from payments.guards import GuardedPayments
from payments.mock import MockPayments
from scoring.schemas import ReviewClaim, ReviewSort
from tasks.schemas import HardConstraints
from tasks.engine import build_task
from tests.fixtures.scoring import FIXTURE_MANIFEST, InMemoryCatalog, feasible_task


NOW = datetime(2026, 10, 31, tzinfo=timezone.utc)


def make_executor(task):
    catalog = InMemoryCatalog(); backend = MockPayments()
    return backend, InMemoryToolExecutor(catalog, GuardedPayments(backend, catalog), task_id=task.id,
        agent_id="agent-1", budget_cap=task.hard_constraints.max_total, clock=lambda: NOW)


def test_end_to_end_purchase_captures_and_scores():
    task = feasible_task()
    backend, executor = make_executor(task)
    actions = [
        ParseIntent(raw_message=task.raw_message, category="running-shoes", max_total=Decimal("100"), assumptions=("size 12",)),
        SearchCatalog(query="", filters={"category": "running-shoes"}),
        GetProduct(product_id="shoe-a"),
        GetReviews(product_id="shoe-a", focus="cushioning", sort=ReviewSort.CRITICAL, limit=2),
        Compare(product_ids=("shoe-a", "shoe-b")),
        SummarizeReviewEvidence(product_id="shoe-a", user_context="support",
            claims=(ReviewClaim(concern="cushioning", claim="support evidence",
                                review_ids=("review-a-positive", "review-a-critical")),)),
        ProposePurchase(product_id="shoe-a", variant="12", expected_total=Decimal("89"), assumptions=("size 12",)),
    ]
    # Pending ID is deterministic from the payment guard.
    from payments.guards import idempotency_key
    actions.append(ConfirmAndPay(pending_order_id=idempotency_key(task.id, "agent-1", "shoe-a", "12"), user_confirmed=True))
    episode = run_episode(episode_id="ep-1", task=task, agent_id="agent-1", generation_id="gen-1",
                          policy=ScriptedPolicy(actions), executor=executor, seed=7, clock=lambda: NOW)
    assert episode.termination == "success" and not episode.killed
    assert len(backend.ledger) == 1 and episode.score_components["gate"] == 1
    assert episode.model_dump(mode="json")["episode_id"] == "ep-1"


def test_impossible_task_reports_no_match_correctly():
    catalog = InMemoryCatalog()
    task = build_task(task_id="impossible-1", catalog_snapshot_id="snap", catalog=catalog, manifest_hash=FIXTURE_MANIFEST,
                      constraints=HardConstraints(category="running-shoes", max_total=Decimal("10")), seed=3)
    backend, executor = make_executor(task)
    policy = ScriptedPolicy([
        ParseIntent(raw_message=task.raw_message, category="running-shoes", max_total=Decimal("10"), assumptions=("no variant",)),
        SearchCatalog(query="", filters={"category": "running-shoes"}),
        GetProduct(product_id=task.closest_product_id),
        Compare(product_ids=("shoe-a", "shoe-b")),
        ReportNoMatch(reason="all catalog products exceed budget", closest_product_id=task.closest_product_id,
                      why_it_misses="price is above $10", assumptions=("all-in price",)),
    ])
    episode = run_episode(episode_id="ep-no", task=task, agent_id="agent-1", generation_id="gen-1",
                          policy=policy, executor=executor, seed=3, clock=lambda: NOW)
    assert episode.termination == "no_match" and episode.score_components["quality"] == "1"


def test_invalid_order_terminates_without_payment():
    task = feasible_task(); backend, executor = make_executor(task)
    episode = run_episode(episode_id="ep-bad", task=task, agent_id="agent-1", generation_id="gen-1",
        policy=ScriptedPolicy([SearchCatalog(query="shoe")]), executor=executor, seed=1, clock=lambda: NOW)
    assert episode.termination == "malformed_action" and backend.ledger == []


def test_over_budget_attempt_is_traced_and_instantly_killed():
    task = feasible_task(); backend, executor = make_executor(task)
    actions = [
        ParseIntent(raw_message=task.raw_message, category="running-shoes", max_total=Decimal("100"), assumptions=("size 12",)),
        SearchCatalog(query="", filters={"category": "running-shoes"}), GetProduct(product_id="shoe-a"),
        GetReviews(product_id="shoe-a", limit=2), Compare(product_ids=("shoe-a", "shoe-b")),
        ProposePurchase(product_id="shoe-a", variant="12", expected_total=Decimal("101"), assumptions=("size 12",)),
    ]
    episode = run_episode(episode_id="ep-budget", task=task, agent_id="agent-1", generation_id="gen-1",
                          policy=ScriptedPolicy(actions), executor=executor, seed=1, clock=lambda: NOW)
    assert episode.termination == "instant_kill"
    assert episode.kill_information[0]["rule_id"] == "K003_BUDGET_VIOLATION"
    assert episode.tool_calls[-1].error_code == "BudgetViolation"
    assert backend.ledger == []


class Raising:
    """Policy whose every call raises `exc`; counts calls."""
    def __init__(self, exc):
        self.exc, self.calls = exc, 0

    def next_step(self, task, history, attempt):
        self.calls += 1
        raise self.exc


def run_with(policy, **kw):
    task = feasible_task()
    _, executor = make_executor(task)
    return run_episode(episode_id="ep-r", task=task, agent_id="agent-1", generation_id="gen-1", policy=policy,
                       executor=executor, seed=7, clock=lambda: NOW, **kw)


def test_only_transient_inference_errors_are_retried_never_refusals():
    from agents.model import TRANSIENT_CODES, InferenceError
    assert TRANSIENT_CODES == {"timeout", "transport_error", "invalid_response"}
    assert InferenceError("timeout", "x").retryable and not InferenceError("model_identity_mismatch", "x").retryable
    for code, calls in (("timeout", 2), ("model_identity_mismatch", 1), ("checkpoint_mismatch", 1), ("adapter_not_found", 1)):
        policy = Raising(InferenceError(code, "x"))
        ep = run_with(policy)
        assert ep.termination == "model_failure" and policy.calls == calls, code
    policy = Raising(ValueError("unparseable content"))  # content failures are not retried either
    assert run_with(policy).termination == "model_failure" and policy.calls == 1


def test_episode_wall_clock_cap_stops_a_slow_policy():
    from agents.runner import RunnerConfig
    task = feasible_task()
    actions = [ParseIntent(raw_message=task.raw_message, category="running-shoes", max_total=Decimal("100"), assumptions=("a",)),
               *[SearchCatalog(query="", filters={"category": "running-shoes"})] * 4]
    ticks = iter(range(0, 1000, 100))
    ep = run_with(ScriptedPolicy(actions), config=RunnerConfig(max_episode_seconds=250), monotonic=lambda: next(ticks))
    assert ep.termination == "tool_limit" and "wall-clock" in ep.final_answer and len(ep.tool_calls) == 2
