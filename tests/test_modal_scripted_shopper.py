import datetime as dt
from decimal import Decimal

from agents.actions import ReportNoMatch
from agents.executor import InMemoryToolExecutor
from agents.runner import run_episode
from catalog.providers.base import Product, Review
from catalog.router import ProviderRouter
from catalog.taskgen import generate_tasks
from catalog.training import TrainingCatalog
from modal_app.scripted_shopper import scripted_policy
from payments.guards import GuardedPayments
from payments.mock import MockPayments

T0 = dt.datetime(2023, 9, 30, tzinfo=dt.UTC)
TITLES = ["Insulated Steel Water Bottle", "Plastic Water Bottle Kids", "Hiking Water Bottle Large", "Cotton Running Shirt",
          "Trail Running Shoe", "Yoga Mat Thick", "Camping Water Bottle Clip"] * 4


class Snap:
    def __init__(self):
        self.items = [Product(id=f"P{i:03d}", title=f"{t} {i}", category="Cat", price=Decimal(f"{5 + 2 * i}.00"), source="amazon2023",
                              as_of=T0, attributes={"main_category": "A"}) for i, t in enumerate(TITLES)]

    def iter_products(self, c): yield from (p for p in self.items if p.category == c)
    def review_ids(self, pid): return frozenset(r.id for r in self.get_reviews(pid))
    def search(self, q, f=None):
        words = set(q.lower().split())
        out = [p for p in self.items if words & set(p.title.lower().split())
               and (not f or f.get("max_price") is None or p.price <= Decimal(str(f["max_price"])))]
        return out[:10]
    def get_product(self, pid): return next((p for p in self.items if p.id == pid), None)
    def get_reviews(self, pid, focus=None, limit=10):
        return [Review(id=f"amazon2023:{pid}:{k}", product_id=pid, rating=4.0, text=f"Held up well after {k} months <br /> of use") for k in range(3)][:limit]


def setup():
    cfg = {"live_chat": "elastic_snapshot", "providers": {"elastic_snapshot": {"enabled": True}}}
    cat = TrainingCatalog(ProviderRouter({"elastic_snapshot": Snap()}, cfg))
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
