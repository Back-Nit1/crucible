"""GRPO on the real PEFT backend, tiny random Qwen2 + real pinned Qwen tokenizer (CPU). Skipped like
tests/test_training_torch_backend.py unless torch/peft and CRUCIBLE_TEST_QWEN_TOKENIZER_DIR are available."""
import datetime as dt
import hashlib
import json
import math
from decimal import Decimal

import pytest

from tests.test_training_torch_backend import HP, NOW, tiny_model_dir  # noqa: F401  (fixture; module skips without torch)
import torch  # noqa: E402

from agents.model import StructuredToolCall  # noqa: E402
from modal_app.adapter_artifact import verify_adapter_dir  # noqa: E402
from tests.test_rl_dataset import episode_turns  # noqa: E402
from tests.test_rl_advantage import rollout  # noqa: E402
from training.planning import GRPOConfig, LoRAHyperparameters, build_lora_plan, plan_hash  # noqa: E402
from training.rl.dataset import build_rl_dataset  # noqa: E402
from training.resume import CheckpointStore, RunIdentity  # noqa: E402
from training.shard import parse_shard  # noqa: E402
from training.torch_backend import BackendError, TorchLoraBackend, backend_signature, load_base_model  # noqa: E402
from training.trainer import run_training  # noqa: E402

D = Decimal
GRPO_HP = LoRAHyperparameters(**{**HP.model_dump(), "method": "lora_grpo", "grpo": GRPOConfig(), "lora_dropout": D("0")})


def turns_for(query, n=1):
    return tuple(t.model_copy(update={"tool_call": StructuredToolCall(name="search_catalog", arguments={"query": f"{query} {i}"})})
                 for i, t in enumerate(episode_turns(n)))


def rollouts():
    out = []
    for task, (a, b) in {"t-1": (D("0.9"), D("0.1")), "t-2": (D("0.2"), D("0.6"))}.items():
        g = hashlib.sha256(task.encode()).hexdigest()
        out += [rollout(episode_id=f"{task}-0", task_id=task, group=g, fitness=a, turns=episode_turns(2)),
                rollout(episode_id=f"{task}-1", task_id=task, group=g, sample=1, fitness=b, turns=turns_for("blue boots", 2))]
    return out


def grpo_shard(rows=None):
    out = build_rl_dataset(rows or rollouts(), GRPO_HP.grpo, created_at=NOW)
    return parse_shard(out.dataset.shard, expected_dataset_hash=out.dataset.dataset_hash,
                       expected_manifest_hash=out.manifest.content_hash), out


def backend(model_dir, sh, hp=GRPO_HP, steps=4, **kw):
    model, tok = load_base_model(model_dir, hp, device="cpu", require_cuda_for_large=False)
    return TorchLoraBackend(model=model, tokenizer=tok, shard=sh, hp=hp, total_steps=steps, device="cpu", **kw)


def test_kl_is_zero_at_init_and_old_logprobs_are_the_base(tiny_model_dir):
    sh, _ = grpo_shard()
    b = backend(tiny_model_dir, sh)
    assert b.old_logp == b.ref_logp  # fresh LoRA (B=0) == base: KL(pi || ref) = 0 before any update
    assert [len(x) for x in b.old_logp] == [len(ids) - 1 for ids, _ in b.encoded]
    assert any(a != 0 for row in b.token_advantages for a in row)


def test_loss_is_finite_and_gradients_reach_lora_params_only(tiny_model_dir):
    sh, _ = grpo_shard()
    b = backend(tiny_model_dir, sh)
    loss = b.train_step([0, 1])
    assert math.isfinite(loss)
    lora = {n: p for n, p in b.model.named_parameters() if "lora_" in n}
    assert lora and all(p.requires_grad and p.grad is not None for p in lora.values())
    assert any(float(p.grad.abs().sum()) > 0 for p in lora.values())
    assert all(p.grad is None and not p.requires_grad for n, p in b.model.named_parameters() if "lora_" not in n)


def one_row_shard(advantage):
    """A hand-sealed single-row GRPO shard with a constant advantage on every turn (no group needed at this level)."""
    _, out = grpo_shard()
    header, row = (json.loads(line) for line in out.dataset.shard.splitlines()[:2])
    header["header"]["record_count"] = 1
    row["turn_advantages"] = [advantage] * len(row["turn_advantages"])
    data = ("\n".join(json.dumps(x, sort_keys=True, separators=(",", ":")) for x in (header, row)) + "\n").encode()
    return parse_shard(data, expected_dataset_hash=hashlib.sha256(data).hexdigest(), expected_manifest_hash=out.manifest.content_hash)


@pytest.mark.parametrize("advantage, direction", [(1.0, 1), (-1.0, -1)])
def test_advantage_sign_moves_the_sequence_logprob(tiny_model_dir, advantage, direction):
    hp = LoRAHyperparameters(**{**GRPO_HP.model_dump(), "grpo": GRPOConfig(kl_beta=D("0")), "warmup_steps": 0,
                                "gradient_accumulation_steps": 1})
    b = backend(tiny_model_dir, one_row_shard(advantage), hp=hp, steps=3)
    before = sum(b.old_logp[0])
    for _ in range(3):
        b.train_step([0])
    after = sum(b._frozen_logprobs(adapter=True)[0])
    assert (after - before) * direction > 0


def test_sft_shard_is_refused_by_a_grpo_backend(tiny_model_dir):
    from tests.test_training_torch_backend import shard as sft_shard
    with pytest.raises(BackendError) as err:
        backend(tiny_model_dir, sft_shard()[0])
    assert err.value.code == "algorithm_shard_mismatch"


def run(tmp_path, model_dir, sh, out, stop=None, policy_adapter_dir=None, hp=GRPO_HP, run_id="run-grpo"):
    steps = hp.total_steps(len(sh.examples))
    b = backend(model_dir, sh, hp=hp, steps=steps, policy_adapter_dir=policy_adapter_dir)
    plan = build_lora_plan(out.manifest, base_model="tiny/qwen2", base_revision="a" * 40, gpu="L4",
                           maximum_approved_cost=D("1"), hyperparameters=hp, record_count=len(sh.examples))
    identity = RunIdentity(run_id=run_id, plan_hash=plan_hash(plan), base_model="tiny/qwen2", base_revision="a" * 40,
                           training_manifest_hash=out.manifest.content_hash, dataset_hash=out.dataset.dataset_hash,
                           data_source_model_version=sh.source_model_version, hyperparameters=hp.model_dump(mode="json"),
                           backend_signature=backend_signature())
    store = CheckpointStore(tmp_path, identity, clock=lambda: NOW)
    return run_training(store=store, identity=identity, backend=b, hp=hp, record_count=len(sh.examples),
                        total_budget_seconds=600, gpu="cpu-test", clock=lambda: NOW, stop_after_steps=stop), store


def test_grpo_resume_equals_uninterrupted_run(tiny_model_dir, tmp_path):
    sh, out = grpo_shard()
    whole, _ = run(tmp_path / "whole", tiny_model_dir, sh, out)
    assert whole.status == "final" and whole.step == whole.total_steps == 4
    assert whole.manifest.hyperparameters["method"] == "lora_grpo" and whole.manifest.hyperparameters["grpo"]["kl_beta"] == "0.04"
    assert whole.manifest.training_manifest_hash == out.manifest.content_hash  # the rollout set hash
    first, _ = run(tmp_path / "split", tiny_model_dir, sh, out, stop=2)
    assert first.status == "paused"
    second, store = run(tmp_path / "split", tiny_model_dir, sh, out)  # fresh model/optimizer: old/ref log-probs rebuilt
    assert second.resumed_from_step == 2 and second.manifest.adapter_hash == whole.manifest.adapter_hash
    verify_adapter_dir(second.manifest, store.final_dir)


def test_policy_adapter_is_the_starting_point_and_must_match_the_lora_shape(tiny_model_dir, tmp_path):
    sh, out = grpo_shard()
    first, store = run(tmp_path, tiny_model_dir, sh, out)
    b = backend(tiny_model_dir, sh, policy_adapter_dir=store.final_dir)
    assert b.old_logp != b.ref_logp  # old log-probs come from the adapter being updated, KL is to the base
    for change in ({"lora_rank": 8}, {"lora_alpha": 16}):  # alpha changes the scaling, i.e. the policy
        other = LoRAHyperparameters(**{**GRPO_HP.model_dump(), **change})
        with pytest.raises(BackendError) as err:
            backend(tiny_model_dir, sh, hp=other, policy_adapter_dir=store.final_dir)
        assert err.value.code == "policy_adapter_incompatible"
