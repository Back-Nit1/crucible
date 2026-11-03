"""Wire contract for the Modal training function (no `modal` import). The request carries the whole, content-hashed
dataset shard and an explicit approval: the container re-checks both, so a request cannot ask for more than the human
approved even if the local gate were bypassed."""
from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from modal_app.adapter_artifact import HEX64, RUN_ID_PATTERN
from training.planning import LoRAPlan, ResourceRates


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TrainingApproval(_Frozen):
    ceiling_usd: Decimal = Field(gt=0)          # what the human approved for this training run
    manifest_hash: str = Field(pattern=HEX64)   # approval is bound to exactly this training manifest
    budget_seconds: float = Field(gt=0)         # whole-run wall-clock allowance derived from ceiling / list rates
    rates: ResourceRates                        # dated rates used to derive budget_seconds and the reported cost


class TrainRequest(_Frozen):
    run_id: str = Field(pattern=RUN_ID_PATTERN)
    plan: LoRAPlan
    shard: str = Field(min_length=1)            # utf-8 JSONL, hashed by dataset_hash
    dataset_hash: str = Field(pattern=HEX64)
    approval: TrainingApproval
    stop_after_steps: int | None = Field(default=None, ge=1)  # pause after N steps this launch (resumable smoke tests)


class TrainResponse(_Frozen):
    status: str                                 # "final" | "paused"
    run_id: str
    step: int
    total_steps: int
    resumed_from_step: int
    checkpoint_id: str | None = None            # set only when status == "final"
    manifest: dict | None = None                # ArtifactManifest JSON, only when final
