from decimal import Decimal

import pytest

from modal_app.qwen_toolcalls import MODEL_ID, MODEL_REVISION
from training.gates import (MAX_LAUNCH_SECONDS, TRAIN_CEILING_VAR, TRAIN_MANIFEST_VAR, GateError, affordable_seconds,
                            authorize_training, cost_per_second, list_rates)
from training.planning import LoRAPlan, LoRAHyperparameters

H = "e" * 64
ENV = {"CRUCIBLE_MODAL_TOKEN_ROTATED": "1", "CRUCIBLE_MODAL_BILLING_CONFIRMED": "1", TRAIN_CEILING_VAR: "0.861948",
       TRAIN_MANIFEST_VAR: H}


def plan(**over):
    base = dict(base_model=MODEL_ID, base_revision=MODEL_REVISION, training_manifest_hash=H, record_count=30, gpu="L4",
                hyperparameters=LoRAHyperparameters(), maximum_approved_cost=Decimal("0.5"))
    return LoRAPlan(**{**base, **over})


def code(env, p=None):
    with pytest.raises(GateError) as err:
        authorize_training(p or plan(), env)
    return err.value.code, str(err.value)


def test_nothing_set_names_every_missing_variable():
    c, msg = code({})
    assert c == "training_not_authorized"
    for name in ("CRUCIBLE_MODAL_TOKEN_ROTATED", "CRUCIBLE_MODAL_BILLING_CONFIRMED", TRAIN_CEILING_VAR, TRAIN_MANIFEST_VAR):
        assert name in msg


@pytest.mark.parametrize("drop", ["CRUCIBLE_MODAL_TOKEN_ROTATED", "CRUCIBLE_MODAL_BILLING_CONFIRMED", TRAIN_CEILING_VAR, TRAIN_MANIFEST_VAR])
def test_each_gate_is_individually_required(drop):
    assert code({k: v for k, v in ENV.items() if k != drop})[1].endswith(drop)


@pytest.mark.parametrize("bad", ["0", "-1", "abc", "nan", "inf", ""])
def test_ceiling_must_be_a_positive_finite_number(bad):
    assert code({**ENV, TRAIN_CEILING_VAR: bad})[0] == "training_not_authorized"


def test_flags_must_be_exactly_one():
    assert code({**ENV, "CRUCIBLE_MODAL_BILLING_CONFIRMED": "true"})[0] == "training_not_authorized"


def test_approval_is_bound_to_the_exact_training_manifest():
    assert code({**ENV, TRAIN_MANIFEST_VAR: "f" * 64})[0] == "approved_manifest_mismatch"


def test_plan_must_use_pinned_model_supported_gpu_and_stay_under_the_ceiling():
    assert code(ENV, plan(base_revision="a" * 40))[0] == "unpinned_model"
    assert code(ENV, plan(base_model="other/model"))[0] == "unpinned_model"
    assert code(ENV, plan(gpu="H100"))[0] == "unsupported_gpu"
    assert code(ENV, plan(maximum_approved_cost=Decimal("0.9")))[0] == "plan_exceeds_ceiling"
    assert code({**ENV, TRAIN_CEILING_VAR: "0.0001"}, plan(maximum_approved_cost=Decimal("0.0001")))[0] == "cost_ceiling_too_low"


def test_budget_seconds_never_buy_more_than_the_ceiling():
    approval = authorize_training(plan(), ENV)
    rates = list_rates()
    spend = Decimal(str(approval.budget_seconds)) * cost_per_second(rates)
    assert spend <= Decimal("0.5") and approval.budget_seconds == affordable_seconds(Decimal("0.5"), rates)
    assert approval.manifest_hash == H and approval.rates.as_of and "estimate" in approval.rates.source
    assert MAX_LAUNCH_SECONDS < 45 * 60


def test_approved_ceiling_caps_a_larger_plan_request_only_by_rejecting_it():
    assert authorize_training(plan(maximum_approved_cost=Decimal("0.861948")), ENV).ceiling_usd == Decimal("0.861948")


# --- GRPO: its own approval, bound to the exact rollout set -------------------------------------------------------
from training.gates import RL_CEILING_VAR, RL_ROLLOUTS_VAR  # noqa: E402
from training.planning import GRPOConfig  # noqa: E402

GRPO = LoRAHyperparameters(method="qlora_grpo", grpo=GRPOConfig())
RL_ENV = {"CRUCIBLE_MODAL_TOKEN_ROTATED": "1", "CRUCIBLE_MODAL_BILLING_CONFIRMED": "1", RL_CEILING_VAR: "0.5", RL_ROLLOUTS_VAR: H}


def test_grpo_needs_the_rl_gates_and_sft_approval_does_not_count():
    c, msg = code(ENV, plan(hyperparameters=GRPO))  # SFT ceiling + manifest approval set, RL ones absent
    assert c == "training_not_authorized" and RL_CEILING_VAR in msg and RL_ROLLOUTS_VAR in msg and TRAIN_MANIFEST_VAR not in msg
    approval = authorize_training(plan(hyperparameters=GRPO), RL_ENV)
    assert approval.manifest_hash == H and approval.ceiling_usd == Decimal("0.5")
    assert code(RL_ENV)[0] == "training_not_authorized"  # and RL approval does not unlock SFT


def test_grpo_approval_is_bound_to_the_rollout_set_hash():
    assert code({**RL_ENV, RL_ROLLOUTS_VAR: "f" * 64}, plan(hyperparameters=GRPO))[0] == "approved_manifest_mismatch"
    assert code({**RL_ENV, RL_CEILING_VAR: "0.1"}, plan(hyperparameters=GRPO))[0] == "plan_exceeds_ceiling"
