"""Cost-bounded LoRA planning only; this module cannot launch training."""

from __future__ import annotations

import hashlib
import json
import math
from decimal import Decimal
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

if TYPE_CHECKING:  # planning stays a leaf (pydantic only) so the trainer container does not need the agent/catalog stack
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
    # Added with the real trainer; all defaulted so existing plans/tests keep their meaning.
    seed: int = Field(default=20_261_101, ge=0, lt=2**32)
    warmup_steps: int = Field(default=2, ge=0)
    weight_decay: Decimal = Field(default=Decimal("0"), ge=0)
    max_grad_norm: Decimal = Field(default=Decimal("1.0"), gt=0)
    quantization: Literal["nf4", "none"] = "nf4"  # nf4 = QLoRA (4-bit base); none = 16-bit LoRA
    target_modules: tuple[str, ...] = ("q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj")
    checkpoint_every_steps: int = Field(default=5, ge=1)
    max_steps: int | None = Field(default=None, ge=1)  # hard cap, used by the cost-bounded smoke run

    @model_validator(mode="after")
    def _method_matches_quantization(self) -> "LoRAHyperparameters":
        if (self.method == "qlora_sft") != (self.quantization == "nf4") or self.method not in {"qlora_sft", "lora_sft"}:
            raise ValueError("method must be qlora_sft with nf4 quantization or lora_sft with none")
        return self

    def examples_per_step(self) -> int:
        return self.micro_batch_size * self.gradient_accumulation_steps

    def steps_per_epoch(self, record_count: int) -> int:
        return math.ceil(record_count / self.examples_per_step())

    def total_steps(self, record_count: int) -> int:
        planned = self.epochs * self.steps_per_epoch(record_count)
        return min(planned, self.max_steps) if self.max_steps else planned


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


def plan_hash(plan: LoRAPlan) -> str:
    body = json.dumps(plan.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode()).hexdigest()


def build_lora_plan(
    manifest: "TrainingManifest",
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
