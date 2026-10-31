import datetime as dt
from decimal import Decimal

from agents.actions import (
    Compare,
    ConfirmAndPay,
    GetProduct,
    GetReviews,
    ParseIntent,
    ProposePurchase,
    ReportNoMatch,
    SearchCatalog,
    SummarizeReviewEvidence,
)
from agents.memory import InMemoryMemoryProvider
from agents.model import ScriptedModelAdapter
from memory.checkpoints import CheckpointStore
from payments.guards import idempotency_key
from scoring.schemas import ReviewClaim, ReviewSort
from tasks.engine import build_review_trap, build_task
from tasks.review_signals import LexicalRule, extract_lexical_signals
from tasks.schemas import HardConstraints, ReviewPolarity, TaskSplit
from tests.fixtures.scoring import InMemoryCatalog
from world.evolution import initialize_population
from world.orchestrator import run_generation
from training.curation import curate_survivors
from eval.artifacts import write_evaluation


NOW = dt.datetime(2026, 10, 31, tzinfo=dt.UTC)


def task_set(catalog):
    feasible = build_task(
        task_id="feasible",
        catalog_snapshot_id="snapshot",
        catalog=catalog,
        constraints=HardConstraints(category="running-shoes", max_total=Decimal("95")),
        seed=1,
    ).model_copy(update={"split": TaskSplit.TRAIN})
    impossible = build_task(
        task_id="impossible",
        catalog_snapshot_id="snapshot",
        catalog=catalog,
        constraints=HardConstraints(category="running-shoes", max_total=Decimal("10")),
        seed=2,
    ).model_copy(update={"split": TaskSplit.TRAIN})
    signal = extract_lexical_signals(
        catalog,
        "shoe-a",
        (LexicalRule(
            concern="toe-box",
            phrases=("toe box felt narrow",),
            persona_relevance="runner concerned about fit",
            polarity=ReviewPolarity.NEGATIVE,
        ),),
        extracted_at=NOW,
    ).signals[0]
    base_trap = build_task(
        task_id="review-trap",
        catalog_snapshot_id="snapshot",
        catalog=catalog,
        constraints=HardConstraints(category="running-shoes", max_total=Decimal("100")),
        review_signals=(signal,),
        seed=3,
    ).model_copy(update={"split": TaskSplit.TRAIN})
    trap = build_review_trap(base_trap, "shoe-b", catalog)
    return feasible, impossible, trap


def script(task, agent_id):
    parse = ParseIntent(
        raw_message=task.raw_message,
        category="running-shoes",
        max_total=task.hard_constraints.max_total,
        assumptions=("catalog list price is the all-in fixture total",),
    )
    search = SearchCatalog(query="", filters={"category": "running-shoes"})
    if task.is_impossible:
        return (
            parse,
            search,
            GetProduct(product_id="shoe-a"),
            Compare(product_ids=("shoe-a", "shoe-b")),
            ReportNoMatch(
                reason="all real products exceed the cap",
                closest_product_id="shoe-a",
                why_it_misses="price exceeds the all-in cap",
                assumptions=("catalog list price is the all-in fixture total",),
            ),
        )
    pick = "shoe-b" if task.is_review_trap else "shoe-a"
    other = "shoe-a" if pick == "shoe-b" else "shoe-b"
    review_id = "review-b-critical" if pick == "shoe-b" else "review-a-critical"
    actions = (
        parse,
        search,
        GetProduct(product_id=pick),
        GetProduct(product_id=other),
        GetReviews(product_id=pick, focus="fit", sort=ReviewSort.CRITICAL, limit=2),
        Compare(product_ids=(pick, other)),
        SummarizeReviewEvidence(
            product_id=pick,
            user_context="runner-specific fit",
            claims=(ReviewClaim(
                concern="fit",
                claim="The cited critical review contains product-specific fit evidence.",
                review_ids=(review_id,),
            ),),
        ),
        ProposePurchase(
            product_id=pick,
            variant="12",
            expected_total=catalog_price(pick),
            assumptions=("catalog list price is the all-in fixture total",),
        ),
    )
    return actions + (
        ConfirmAndPay(
            pending_order_id=idempotency_key(task.id, agent_id, pick, "12"),
            user_confirmed=True,
        ),
    )


def catalog_price(product_id):
    return Decimal("99") if product_id == "shoe-b" else Decimal("89")


def test_generation_resume_is_duplicate_free_and_reports_honest_metrics(tmp_path):
    catalog = InMemoryCatalog()
    tasks = task_set(catalog)
    genomes = tuple(
        genome.model_copy(update={
            "search": genome.search.model_copy(update={"minimum_candidates": 2}),
            "reviews": genome.reviews.model_copy(update={"minimum_reviews": 2}),
        })
        for genome in initialize_population(4, seed=41, checkpoint="scripted")
    )
    store = CheckpointStore(tmp_path / "checkpoints")
    memory = InMemoryMemoryProvider()

    def adapter(task, genome):
        return ScriptedModelAdapter({task.id: script(task, genome.id)})

    interrupted = run_generation(
        store=store,
        generation_id="generation-1",
        genomes=genomes,
        tasks=tasks,
        catalog=catalog,
        memory=memory,
        adapter_factory=adapter,
        seed=91,
        max_episodes=5,
        clock=lambda: NOW,
    )
    assert not interrupted.summary.complete
    assert len(interrupted.executed_keys) == 5

    resumed = run_generation(
        store=store,
        generation_id="generation-1",
        genomes=genomes,
        tasks=tasks,
        catalog=catalog,
        memory=memory,
        adapter_factory=adapter,
        seed=91,
        clock=lambda: NOW,
    )
    assert resumed.summary.complete
    assert not set(interrupted.executed_keys) & set(resumed.executed_keys)
    assert len(resumed.episodes) == 12
    assert resumed.summary.survivor_count == 3
    assert resumed.summary.kills_by_rule == {}
    assert resumed.summary.wrong_refusal_rate.value == 0
    assert resumed.summary.correct_refusal_rate.value == 1
    assert resumed.summary.hallucination_rate.value == 0
    assert resumed.summary.review_grounding_rate.value == 1
    assert resumed.summary.review_trap_accuracy.value == 1
    assert resumed.summary.budget_violation_rate.value == 0
    assert resumed.summary.mock_payment_count == 8
    assert resumed.summary.total_cost == 0
    assert set(genome.id for genome in resumed.next_generation) != set(genome.id for genome in genomes)

    survivor_episodes = tuple(
        episode for episode in resumed.episodes if episode.agent_id in resumed.survivor_ids
    )
    curated = curate_survivors(
        survivor_episodes,
        {task.id: task for task in tasks},
        catalog,
        catalog_hash="a" * 64,
        task_version="fixture-tasks-v1",
        rule_version="kills-v1",
        model_version="scripted-v1",
        created_at=NOW,
    )
    assert len(curated.records) == 3
    assert set(curated.manifest.source_task_splits.values()) == {TaskSplit.TRAIN}
    assert len(curated.manifest.content_hash) == 64
    json_path, markdown_path = write_evaluation(
        resumed.evaluation, tmp_path / "reports", "generation-1"
    )
    assert json_path.exists() and markdown_path.exists()

    repeated = run_generation(
        store=store,
        generation_id="generation-1",
        genomes=genomes,
        tasks=tasks,
        catalog=catalog,
        memory=memory,
        adapter_factory=adapter,
        seed=91,
        clock=lambda: NOW,
    )
    assert repeated.executed_keys == ()
    assert [episode.episode_id for episode in repeated.episodes] == [
        episode.episode_id for episode in resumed.episodes
    ]
