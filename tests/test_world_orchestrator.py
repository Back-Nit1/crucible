from datetime import datetime, timezone
from decimal import Decimal

from agents.actions import (
    Compare, ConfirmAndPay, GetProduct, GetReviews, ParseIntent, ProposePurchase,
    ReportNoMatch, SearchCatalog,
)
from agents.model import ScriptedModelAdapter
from payments.guards import idempotency_key
from tasks.batch import BatchConfig, ReviewTrapTemplate, generate_batch
from tasks.engine import SplitConfig
from tasks.schemas import ReviewSignal
from tests.fixtures.scoring import InMemoryCatalog
from world.evolution import initialize_population
from world.orchestrator import run_generation


NOW = datetime(2026, 10, 31, tzinfo=timezone.utc)


def snapshot():
    catalog = InMemoryCatalog()
    catalog.products = {key: product.model_copy(update={"variants": {}})
                        for key, product in catalog.products.items()}
    return catalog


def batch(catalog):
    template = ReviewTrapTemplate(
        category="running-shoes", review_adjusted_best="shoe-b",
        signals=(ReviewSignal(concern="cushioning", product_id="shoe-a",
            claim="fixture review explicitly says cushioning remained supportive",
            supporting_review_ids=("review-a-positive",),
            extraction_provenance="human-verified test fixture"),),
    )
    return generate_batch(catalog, seed=17,
        config=BatchConfig(size=10, feasible_percent=70,
                           split=SplitConfig(train=100, validation=0, test=0)),
        review_templates=(template,))


def scripts(tasks, genomes, catalog, generation_id):
    result = {}
    for genome in genomes:
        for task in tasks:
            products = catalog.enumerate_products(task.hard_constraints.category)
            compare_ids = tuple(product.id for product in products[:2])
            common = [
                ParseIntent(raw_message=task.raw_message, category=task.hard_constraints.category,
                            max_total=task.hard_constraints.max_total,
                            assumptions=("catalog price is the all-in fixture total",)),
                SearchCatalog(query="", filters={"category": task.hard_constraints.category}),
            ]
            if task.is_impossible:
                actions = common + [
                    GetProduct(product_id=task.closest_product_id),
                    Compare(product_ids=compare_ids),
                    ReportNoMatch(reason="no enumerated product is within budget",
                                  closest_product_id=task.closest_product_id,
                                  why_it_misses="catalog price exceeds the maximum total",
                                  assumptions=("catalog price is all-in",)),
                ]
            else:
                selected = task.review_adjusted_best or task.best_value_reference
                product = catalog.get_product(selected)
                actions = common + [GetProduct(product_id=selected), Compare(product_ids=compare_ids)]
                if catalog.complete_review_ids(selected):
                    actions.append(GetReviews(product_id=selected, focus="shopper fit", limit=2))
                actions += [
                    ProposePurchase(product_id=selected, variant="default",
                                    expected_total=product.price,
                                    assumptions=("no size or stock fact is claimed",)),
                    ConfirmAndPay(pending_order_id=idempotency_key(
                        task.id, genome.id, selected, "default"), user_confirmed=True),
                ]
            episode_id = f"{generation_id}:{genome.id}:{task.id}"
            result[episode_id] = tuple(actions)
    return result


def test_seeded_generation_resume_curation_and_reports_are_end_to_end():
    catalog = snapshot(); task_batch = batch(catalog)
    assert (task_batch.feasible_count, task_batch.impossible_count,
            task_batch.review_trap_count) == (7, 3, 1)
    genomes = initialize_population(2, 9)
    adapter = ScriptedModelAdapter(scripts(task_batch.tasks, genomes, catalog, "gen-1"))
    partial = run_generation(
        generation_id="gen-1", seed=9, tasks=task_batch.tasks, genomes=genomes,
        catalog=catalog, model=adapter, max_new_episodes=3, clock=lambda: NOW, created_at=NOW)
    assert partial.checkpoint.status == "running"
    assert len(partial.checkpoint.completed_episode_keys) == 3

    resumed = run_generation(
        generation_id="gen-1", seed=9, tasks=task_batch.tasks, genomes=genomes,
        catalog=catalog, model=adapter, checkpoint=partial.checkpoint,
        existing_episodes=partial.episodes, clock=lambda: NOW, created_at=NOW)
    assert resumed.checkpoint.status == "complete"
    assert len(resumed.episodes) == 20
    assert len(set(resumed.checkpoint.completed_episode_keys)) == 20
    assert set(partial.checkpoint.completed_episode_keys) <= set(resumed.checkpoint.completed_episode_keys)
    assert resumed.summary.survivor_count == 2
    assert resumed.summary.kills_by_rule == {}
    assert resumed.summary.wrong_refusals == resumed.summary.hallucinations == 0
    assert resumed.summary.review_grounding == Decimal("1")
    assert resumed.summary.review_trap_accuracy == Decimal("1")
    assert resumed.summary.mean_latency_ms == Decimal("0")
    assert resumed.summary.mock_payment_count == 14
    assert resumed.curation is not None
    assert len(resumed.curation.records) == 17
    assert list(resumed.curation.exclusions.values()).count("duplicate_trace") == 3
    assert resumed.curation.manifest.catalog_hash == catalog.manifest_hash
    assert resumed.evaluation.metrics["success_rate"].value == Decimal("1")
    assert '"success_rate"' in resumed.evaluation_json
    assert "| success_rate |" in resumed.evaluation_markdown


def test_resume_rejects_checkpoint_without_persisted_episode_records():
    catalog = snapshot(); task_batch = batch(catalog); genomes = initialize_population(1, 3)
    adapter = ScriptedModelAdapter(scripts(task_batch.tasks, genomes, catalog, "gen-bad"))
    partial = run_generation(generation_id="gen-bad", seed=3, tasks=task_batch.tasks,
        genomes=genomes, catalog=catalog, model=adapter, max_new_episodes=1,
        clock=lambda: NOW, created_at=NOW)
    import pytest
    with pytest.raises(ValueError, match="persisted episode"):
        run_generation(generation_id="gen-bad", seed=3, tasks=task_batch.tasks,
            genomes=genomes, catalog=catalog, model=adapter, checkpoint=partial.checkpoint,
            existing_episodes=(), clock=lambda: NOW, created_at=NOW)
