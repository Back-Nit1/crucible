from agents.actions import ReportNoMatch
from agents.executor import InMemoryToolExecutor
from agents.runner import run_episode
from catalog.taskgen import generate_tasks
from tests.fixtures.snapshot import training_catalog
from modal_app.scripted_shopper import scripted_policy
from payments.guards import GuardedPayments
from payments.mock import MockPayments

def setup():
    cat = training_catalog()
    return cat, generate_tasks(cat, ["Cat"], 8, seed=4, snapshot_id="snap")


def play(task, cat):
    guarded = GuardedPayments(MockPayments(auto_approve=True), cat)
    ex = InMemoryToolExecutor(cat, guarded, task_id=task.id, agent_id="a1", budget_cap=task.hard_constraints.max_total)
    return run_episode(episode_id=f"e-{task.id}", task=task, agent_id="a1", generation_id="g0",
                       policy=scripted_policy(task, cat, "a1"), executor=ex, seed=1)


def test_feasible_task_runs_to_a_grounded_purchase_with_no_kill():
    cat, tasks = setup()
    task = next(t for t in tasks if not t.is_impossible)
    ep = play(task, cat)
    assert ep.termination == "success" and not ep.killed and ep.recommended_products == (task.best_value_reference,)
    assert [c.action.type for c in ep.tool_calls][:1] == ["parse_intent"] and ep.tool_calls[-1].action.type == "confirm_and_pay"
    claim = next(c for c in ep.tool_calls if c.action.type == "summarize_review_evidence").action.claims[0]
    assert "<br" not in claim.claim and claim.review_ids[0].startswith("amazon2023:")  # real id, cleaned excerpt


def test_impossible_task_ends_in_a_correct_no_match_with_a_real_closest_product():
    cat, tasks = setup()
    task = next(t for t in tasks if t.is_impossible)
    ep = play(task, cat)
    assert ep.termination == "no_match" and isinstance(ep.refusal, ReportNoMatch) and not ep.killed
    assert ep.refusal.closest_product_id == task.closest_product_id
