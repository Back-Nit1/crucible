"""Cost-bounded LoRA planning only; this module cannot launch training."""

from __future__ import annotations

import hashlib
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from training.curation import TrainingManifest


class PlanModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class LoRAHyperparameters(PlanModel):
    method: str = "qlora_sft"
    epochs: int = Field(default=1, ge=1, le=5)
    learning_rate: Decimal = Field(default=Decimal("0.0002"), gt=0)
    lora_rank: int = Field(default=16, ge=1, le=256)
    lora_alpha: int = Field(default=32, ge=1, le=512)
    lora_dropout: Decimal = Field(default=Decimal("0.05"), ge=0, lt=1)
    max_sequence_length: int = Field(default=2048, ge=128, le=32768)
    micro_batch_size: int = Field(default=1, ge=1)
    gradient_accumulation_steps: int = Field(default=8, ge=1)


class LoRAPlan(PlanModel):
    plan_version: str = "1.0"
    base_model: str = Field(min_length=1)
    base_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    training_manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    record_count: int = Field(gt=0)
    gpu: str = Field(min_length=1)
    hyperparameters: LoRAHyperparameters
    maximum_approved_cost: Decimal = Field(gt=0)


class ResourceRates(PlanModel):
    gpu_per_second: Decimal = Field(ge=0)
    cpu_cores: Decimal = Field(ge=0)
    cpu_per_core_second: Decimal = Field(ge=0)
    memory_gib: Decimal = Field(ge=0)
    memory_per_gib_second: Decimal = Field(ge=0)
    source: str = Field(min_length=1)
    as_of: str = Field(min_length=1)


class TrainingCostEstimate(PlanModel):
    duration_seconds: int = Field(gt=0)
    gpu_cost: Decimal
    cpu_cost: Decimal
    memory_cost: Decimal
    total_cost: Decimal
    within_approved_budget: bool
    rates_source: str
    rates_as_of: str


def build_lora_plan(
    manifest: TrainingManifest,
    *,
    base_model: str,
    base_revision: str,
    gpu: str,
    maximum_approved_cost: Decimal,
    hyperparameters: LoRAHyperparameters = LoRAHyperparameters(),
) -> LoRAPlan:
    if not manifest.source_episode_ids:
        raise ValueError("LoRA planning requires at least one curated grounded trace")
    return LoRAPlan(
        base_model=base_model,
        base_revision=base_revision,
        training_manifest_hash=manifest.content_hash,
        record_count=len(manifest.source_episode_ids),
        gpu=gpu,
        hyperparameters=hyperparameters,
        maximum_approved_cost=maximum_approved_cost,
    )


def estimate_training_cost(
    plan: LoRAPlan,
    *,
    duration_seconds: int,
    rates: ResourceRates,
) -> TrainingCostEstimate:
    """Use caller-supplied, dated rates; never hard-code a possibly stale price."""
    seconds = Decimal(duration_seconds)
    gpu = seconds * rates.gpu_per_second
    cpu = seconds * rates.cpu_cores * rates.cpu_per_core_second
    memory = seconds * rates.memory_gib * rates.memory_per_gib_second
    total = gpu + cpu + memory
    return TrainingCostEstimate(
        duration_seconds=duration_seconds,
        gpu_cost=gpu,
        cpu_cost=cpu,
        memory_cost=memory,
        total_cost=total,
        within_approved_budget=total <= plan.maximum_approved_cost,
        rates_source=rates.source,
        rates_as_of=rates.as_of,
    )


def deterministic_inspection_sample(records: tuple, *, count: int, seed: int) -> tuple:
    """Select a stable sample for a human; selection is not human validation."""
    if count < 0:
        raise ValueError("count cannot be negative")
    ranked = sorted(
        records,
        key=lambda record: (
            hashlib.sha256(f"{seed}|{record.normalized_hash}".encode()).hexdigest(),
            record.source_episode_id,
        ),
    )
    return tuple(ranked[:count])
