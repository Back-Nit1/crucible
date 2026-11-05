"""Fail-closed authorization and cost bounds for GPU training. Pure functions over an env mapping: nothing here can
start a GPU, and nothing sets the variables (only the human does, after rotating the token, adding billing and
approving a ceiling for THIS training manifest)."""
from __future__ import annotations

import os
from collections.abc import Mapping
from decimal import Decimal

from modal_app.qwen_toolcalls import (CPU_CORES, CPU_RATE_USD_PER_CORE_SECOND, GPU_RATE_USD_PER_SECOND, GPU_TYPE,
                                      MEMORY_GIB, MEMORY_RATE_USD_PER_GIB_SECOND, MODEL_ID, MODEL_REVISION)
from modal_app.train_protocol import TrainingApproval
from training.planning import LoRAPlan, ResourceRates

LAUNCH_FLAGS = ("CRUCIBLE_MODAL_TOKEN_ROTATED", "CRUCIBLE_MODAL_BILLING_CONFIRMED")
TRAIN_CEILING_VAR = "CRUCIBLE_MODAL_TRAINING_CEILING_USD"
TRAIN_MANIFEST_VAR = "CRUCIBLE_MODAL_TRAINING_APPROVED_MANIFEST_HASH"
RL_CEILING_VAR = "CRUCIBLE_MODAL_RL_CEILING_USD"                   # GRPO has its own approval ...
RL_ROLLOUTS_VAR = "CRUCIBLE_MODAL_RL_APPROVED_ROLLOUTS_HASH"        # ... bound to the exact rollout set (training.rl.dataset)
MAX_LAUNCH_SECONDS = 2580   # 43 min: leaves headroom under the 45 min Modal timeout for the soft stop + finalize
RATES_AS_OF = "2026-10-31"  # when docs/spikes/modal-qwen.md recorded these list rates


class GateError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code


def list_rates() -> ResourceRates:
    return ResourceRates(gpu_per_second=Decimal(str(GPU_RATE_USD_PER_SECOND)), cpu_cores=Decimal(str(CPU_CORES)),
                         cpu_per_core_second=Decimal(str(CPU_RATE_USD_PER_CORE_SECOND)), memory_gib=Decimal(str(MEMORY_GIB)),
                         memory_per_gib_second=Decimal(str(MEMORY_RATE_USD_PER_GIB_SECOND)),
                         source="Modal list rates recorded in modal_app/qwen_toolcalls.py (estimate; Modal billing is the truth)",
                         as_of=RATES_AS_OF)


def cost_per_second(rates: ResourceRates) -> Decimal:
    return rates.gpu_per_second + rates.cpu_cores * rates.cpu_per_core_second + rates.memory_gib * rates.memory_per_gib_second


def affordable_seconds(ceiling: Decimal, rates: ResourceRates) -> int:
    return int(ceiling / cost_per_second(rates))


def gate_vars(plan: LoRAPlan) -> tuple[str, str]:
    """(ceiling variable, approved-data-hash variable) for this plan's algorithm."""
    return (RL_CEILING_VAR, RL_ROLLOUTS_VAR) if plan.hyperparameters.algorithm == "grpo" else (TRAIN_CEILING_VAR, TRAIN_MANIFEST_VAR)


def authorize_training(plan: LoRAPlan, env: Mapping[str, str] | None = None) -> TrainingApproval:
    """Return the approval to send with the run, or raise naming exactly what is missing / inconsistent. SFT and GRPO
    are approved separately: GRPO reads the RL ceiling and the approved rollout-set hash, never the SFT ones."""
    env = os.environ if env is None else env
    ceiling_var, hash_var = gate_vars(plan)
    missing = [name for name in LAUNCH_FLAGS if env.get(name) != "1"]
    try:
        ceiling = Decimal(env.get(ceiling_var, ""))
    except Exception:
        ceiling = Decimal(0)
    if not ceiling.is_finite() or ceiling <= 0:
        ceiling = Decimal(0)
        missing.append(ceiling_var)
    approved_hash = env.get(hash_var, "")
    if not approved_hash:
        missing.append(hash_var)
    if missing:
        raise GateError("training_not_authorized", "missing confirmations: " + ", ".join(missing))
    if approved_hash != plan.training_manifest_hash:
        raise GateError("approved_manifest_mismatch", f"{hash_var} approves a different training data set")
    if (plan.base_model, plan.base_revision) != (MODEL_ID, MODEL_REVISION):
        raise GateError("unpinned_model", "plan does not use the pinned base model and revision")
    if plan.gpu != GPU_TYPE:
        raise GateError("unsupported_gpu", f"only {GPU_TYPE} has a validated memory/cost envelope")
    if plan.maximum_approved_cost > ceiling:
        raise GateError("plan_exceeds_ceiling", "the plan asks for more than the approved training ceiling")
    rates = list_rates()
    budget = min(affordable_seconds(min(plan.maximum_approved_cost, ceiling), rates), MAX_LAUNCH_SECONDS * 4)
    if budget < 60:
        raise GateError("cost_ceiling_too_low", "the approved ceiling buys less than 60 seconds of L4")
    return TrainingApproval(ceiling_usd=ceiling, manifest_hash=approved_hash, budget_seconds=float(budget), rates=rates)
