"""Phase 4: EpisodeRecord <-> traces boundary and the repository-backed MemoryProvider, incl. leakage/kill/fitness gates."""
from datetime import datetime, timezone
from decimal import Decimal


from agents.actions import (Compare, ConfirmAndPay, GetProduct, GetReviews, ParseIntent, ProposePurchase,
                            SearchCatalog, SummarizeReviewEvidence)
from agents.executor import InMemoryToolExecutor
from agents.memory import MemoryProvider, RetrievalRequest
from agents.runner import ScriptedPolicy, run_episode
from memory import InMemoryTraceRepository
from memory.elastic import ElasticTraceRepository
from memory.episodes import RepositoryMemoryProvider, episode_from_trace, trace_from_episode
from payments.guards import GuardedPayments, idempotency_key
from payments.mock import MockPayments
from scoring.schemas import ReviewClaim, ReviewSort
from tasks.schemas import TaskSplit
from tests.fixtures.scoring import InMemoryCatalog, feasible_task
from world.evolution import initialize_population

NOW = datetime(2026, 10, 31, tzinfo=timezone.utc)
GENOME = initialize_population(1, 5)[0]


def run(split=TaskSplit.TRAIN, agent="agent-1", ep="ep-1", total="89", cited=("review-a-positive", "review-a-critical")):
    task = feasible_task(id=f"task-{ep}", split=split, held_out_category=split is TaskSplit.HELD_OUT_CATEGORY)
    catalog = InMemoryCatalog()
    ex = InMemoryToolExecutor(catalog, GuardedPayments(MockPayments(), catalog), task_id=task.id, agent_id=agent,
                              budget_cap=task.hard_constraints.max_total, clock=lambda: NOW)
    steps = [ParseIntent(raw_message=task.raw_message, category="running-shoes", max_total=Decimal("100"), assumptions=("size 12",)),
             SearchCatalog(query="", filters={"category": "running-shoes"}), GetProduct(product_id="shoe-a"),
             GetReviews(product_id="shoe-a", focus="cushioning", sort=ReviewSort.CRITICAL, limit=2),
             Compare(product_ids=("shoe-a", "shoe-b")),
             SummarizeReviewEvidence(product_id="shoe-a", user_context="support",
                                     claims=(ReviewClaim(concern="cushioning", claim="support", review_ids=cited),)),
             ProposePurchase(product_id="shoe-a", variant="12", expected_total=Decimal(total), assumptions=("size 12",)),
             ConfirmAndPay(pending_order_id=idempotency_key(task.id, agent, "shoe-a", "12"), user_confirmed=True)]
    return task, run_episode(episode_id=ep, task=task, agent_id=agent, generation_id="gen-1",
                             policy=ScriptedPolicy(steps), executor=ex, seed=11, clock=lambda: NOW)


def test_trace_preserves_the_entire_episode_and_provenance():
    task, ep = run()
    t = trace_from_episode(ep, task, GENOME, generation=3)
    assert episode_from_trace(t) == ep  # lossless round trip: ordered calls, args, refs, timestamps, answer
    assert [c["sequence"] for c in t.episode["tool_calls"]] == list(range(8))
    assert (t.split, t.catalog_hash, t.seed, t.generation_id, t.generation) == ("train", task.catalog_manifest_hash, 11, "gen-1", 3)
    assert t.genome["id"] == GENOME.id and t.scored and not t.killed
    assert t.products_considered[:1] == ["shoe-a"] and set(t.review_ids_cited) == {"review-a-positive", "review-a-critical"}
    assert [p["event"] for p in t.payment_events] == ["order_created", "captured"] and t.score_components["gate"] == 1
    assert t.final_answer == ep.final_answer and t.fitness == float(Decimal(ep.score_components["fitness"]))


def test_killed_trace_keeps_rule_version_and_evidence():
    task, ep = run(total="120")  # over-budget proposal attempt -> K003, traced before any money moves
    t = trace_from_episode(ep, task)
    assert t.killed and t.kill_reason == "K003_BUDGET_VIOLATION" and t.kill_rule_version == 1
    assert t.kills[0]["evidence"] and not t.scored and t.payment_events[0]["error"] == "BudgetViolation"


def test_memory_provider_contract_and_retrieval_gates():
    repo = InMemoryTraceRepository()
    mem = RepositoryMemoryProvider(repo)
    assert isinstance(mem, MemoryProvider.__class__) or hasattr(mem, "retrieve")  # structural Protocol
    good = [run(ep=f"good-{i}", agent=f"agent-{i}") for i in range(3)]
    for task, ep in good:
        mem.store(ep, split=task.split, category="running-shoes", fitness=float(Decimal(ep.score_components["fitness"])), task=task)
    test_task, test_ep = run(split=TaskSplit.TEST, ep="leak")
    mem.store(test_ep, split=TaskSplit.TEST, category="running-shoes", fitness=1, task=test_task)
    held_task, held_ep = run(split=TaskSplit.HELD_OUT_CATEGORY, ep="held")
    mem.store(held_ep, split=TaskSplit.HELD_OUT_CATEGORY, category="running-shoes", fitness=1, task=held_task)
    dead_task, dead_ep = run(ep="dead", total="120")
    mem.store(dead_ep, split=TaskSplit.TRAIN, category="running-shoes", fitness=1, task=dead_task)
    stored = {t.episode_id for t in repo.traces}
    assert stored == {"good-0", "good-1", "good-2"}  # test, held-out and killed never stored for retrieval
    # even if a protected/killed trace reaches the repository by another path (dashboard record), retrieval refuses it
    mem.record(test_ep, test_task); mem.record(dead_ep, dead_task); mem.record(held_ep, held_task)
    req = lambda k, floor=0.0, split=TaskSplit.TRAIN: RetrievalRequest("new", split, "running-shoes", "running shoes cushioning", k, floor)
    got = mem.retrieve(req(2))
    assert len(got) == 2 and {e.episode_id for e in got} <= {"good-0", "good-1", "good-2"}  # exact k
    assert [e.episode_id for e in mem.retrieve(req(3))] == sorted(e.episode_id for e in good_eps(good))  # stable ties by id
    assert mem.retrieve(req(5, floor=2.0)) == ()  # below threshold never returned
    assert mem.retrieve(req(3, split=TaskSplit.TEST)) == () and mem.retrieve(req(0)) == ()


def good_eps(good):
    return [ep for _, ep in good]


def test_unscored_episode_is_never_retrievable():
    task, ep = run()
    unscored = ep.model_copy(update={"score_components": {}})
    repo = InMemoryTraceRepository()
    RepositoryMemoryProvider(repo).record(unscored, task)
    assert repo.similar("running shoes", k=3, min_fitness=0.0) == []


def test_elastic_repository_fails_closed_on_malformed_and_ineligible_hits():
    task, ep = run()
    good = trace_from_episode(ep, task).model_dump()
    leaked = {**good, "episode_id": "x", "split": "test"}
    dead = {**good, "episode_id": "y", "killed": True}
    weak = {**good, "episode_id": "z", "fitness": 0.01}
    bad = {**good, "episode_id": "w", "fitness": "not-a-number"}
    hits = [{"_source": d} for d in (good, leaked, dead, weak, bad, {"garbage": 1})]

    class FakeEs:
        def ix(self, n): return n
        def call(self, m, p, body=None, **k): return {"hits": {"hits": hits}}
    got = ElasticTraceRepository(FakeEs(), embed=lambda t, kind="ingest": [0.0]).similar("shoes", k=6, min_fitness=0.5)
    assert [t.episode_id for t in got] == ["ep-1"]
