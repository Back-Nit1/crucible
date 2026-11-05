import datetime as dt
from decimal import Decimal

import pytest

from tests.fixtures.scoring import InMemoryCatalog
from tests.test_training_curation import successful_episode
from training.curation import curate_survivors
from training.planning import (
    ResourceRates,
    build_lora_plan,
    deterministic_inspection_sample,
    estimate_training_cost,
)


def curated():
    task, episode = successful_episode()
    return curate_survivors(
        (episode,),
        {task.id: task},
        InMemoryCatalog(),
        catalog_hash="a" * 64,
        task_version="tasks-v1",
        rule_version="kills-v1",
        model_version="base-qwen-a09a3545",
        created_at=dt.datetime(2026, 10, 31, tzinfo=dt.UTC),
    )


def test_lora_plan_is_manifest_bound_and_cost_requires_dated_rates():
    result = curated()
    plan = build_lora_plan(
        result.manifest,
        base_model="Qwen/Qwen2.5-7B-Instruct",
        base_revision="a09a35458c702b33eeacc393d103063234e8bc28",
        gpu="L4",
        maximum_approved_cost=Decimal("5"),
    )
    rates = ResourceRates(
        gpu_per_second=Decimal("0.0002"),
        cpu_cores=Decimal("2"),
        cpu_per_core_second=Decimal("0.00001"),
        memory_gib=Decimal("32"),
        memory_per_gib_second=Decimal("0.000002"),
        source="test-only fixed rates",
        as_of="2026-10-31",
    )
    estimate = estimate_training_cost(plan, duration_seconds=3600, rates=rates)
    assert plan.training_manifest_hash == result.manifest.content_hash
    assert plan.record_count == 1
    assert estimate.total_cost == Decimal("1.022400")
    assert estimate.within_approved_budget
    assert estimate.rates_source == "test-only fixed rates"


def test_empty_manifest_cannot_be_planned_and_inspection_sample_is_seeded():
    result = curated()
    empty = result.manifest.model_copy(update={"source_episode_ids": ()})
    with pytest.raises(ValueError, match="grounded trace"):
        build_lora_plan(
            empty,
            base_model="Qwen/Qwen2.5-7B-Instruct",
            base_revision="a09a35458c702b33eeacc393d103063234e8bc28",
            gpu="L4",
            maximum_approved_cost=Decimal("1"),
        )
    assert deterministic_inspection_sample(result.records, count=1, seed=9) == result.records


def test_step_arithmetic_and_method_quantization_consistency():
    from training.planning import LoRAHyperparameters, plan_hash
    hp = LoRAHyperparameters(epochs=2, micro_batch_size=2, gradient_accumulation_steps=4)
    assert (hp.examples_per_step(), hp.steps_per_epoch(30), hp.total_steps(30)) == (8, 4, 8)
    assert LoRAHyperparameters(epochs=2, max_steps=3).total_steps(30) == 3  # hard cap for the smoke run
    with pytest.raises(ValueError):
        LoRAHyperparameters(method="qlora_sft", quantization="none")
    assert LoRAHyperparameters(method="lora_sft", quantization="none").quantization == "none"
    plan = build_lora_plan(curated().manifest, base_model="m", base_revision="a" * 40, gpu="L4",
                           maximum_approved_cost=Decimal("1"))
    assert plan_hash(plan) == plan_hash(plan.model_copy()) and len(plan_hash(plan)) == 64


def test_grpo_hyperparameters_need_their_config_and_leave_sft_dumps_unchanged():
    from training.planning import GRPOConfig, LoRAHyperparameters
    sft = LoRAHyperparameters()
    assert sft.algorithm == "sft" and "grpo" not in sft.model_dump(mode="json")  # SFT plan hashes / run identities stay stable
    grpo = LoRAHyperparameters(method="qlora_grpo", grpo=GRPOConfig())
    assert grpo.algorithm == "grpo" and grpo.model_dump(mode="json")["grpo"]["kl_beta"] == "0.04"
    assert LoRAHyperparameters.model_validate(grpo.model_dump(mode="json")) == grpo
    for bad in ({"method": "qlora_grpo"}, {"method": "qlora_sft", "grpo": GRPOConfig()},
                {"method": "lora_grpo", "grpo": GRPOConfig()}):  # lora_* needs quantization none
        with pytest.raises(ValueError):
            LoRAHyperparameters(**bad)
    with pytest.raises(ValueError):
        GRPOConfig(min_group_size=1)
    with pytest.raises(ValueError):
        GRPOConfig(policy_checkpoint="qwen-lora-0123456789ab")  # an adapter policy must name its adapter
