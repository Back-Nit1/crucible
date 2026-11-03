import datetime as dt
import json
from decimal import Decimal

import pytest

from modal_app.adapter_artifact import ADAPTER_CONFIG, ADAPTER_WEIGHTS, load_manifest
from modal_app.qwen_toolcalls import MODEL_ID, MODEL_REVISION
from modal_app.train_protocol import TrainRequest
from tests.test_training_dataset import curated, rebuilt
from tests.test_training_gates import ENV, TRAIN_CEILING_VAR
from training.dataset import build_dataset
from training.gates import GateError, authorize_training
from training.planning import LoRAHyperparameters, build_lora_plan
from training.resume import ResumeError
from training.service import execute
from training.shard import ShardError

NOW = dt.datetime(2026, 11, 1, tzinfo=dt.timezone.utc)
HP = LoRAHyperparameters(epochs=2, gradient_accumulation_steps=2, checkpoint_every_steps=1, max_steps=3)


class Backend:
    def __init__(self):
        self.n, self.seen = 0, []

    def train_step(self, idx):
        self.seen.append(tuple(idx))
        self.n += 1
        return 1.0 / self.n

    def capture(self, directory):
        (directory / "s.json").write_text(json.dumps({"n": self.n}))

    def restore(self, directory):
        self.n = json.loads((directory / "s.json").read_text())["n"]

    def export_adapter(self, directory):
        (directory / ADAPTER_CONFIG).write_text("{}")
        (directory / ADAPTER_WEIGHTS).write_text(f"w{self.n}")


def request(**over):
    records, manifest = curated()
    many = tuple(records[0].model_copy(update={"source_episode_id": f"ep-{i}", "messages": (
        {"role": "user", "content": f"need shoes {i}"}, *records[0].messages[1:])}) for i in range(4))
    manifest = rebuilt(many, manifest)
    data = build_dataset(many, manifest)
    plan = build_lora_plan(manifest, base_model=MODEL_ID, base_revision=MODEL_REVISION, gpu="L4",
                           maximum_approved_cost=Decimal("0.5"), hyperparameters=HP)
    env = {**ENV, "CRUCIBLE_MODAL_TRAINING_APPROVED_MANIFEST_HASH": manifest.content_hash}
    fields = dict(run_id="run-smoke", plan=plan, shard=data.shard.decode(), dataset_hash=data.dataset_hash,
                  approval=authorize_training(plan, env))
    return TrainRequest(**{**fields, **over})


def run(tmp_path, req, backend=None, **kw):
    backend = backend or Backend()
    return execute(req, runs_root=tmp_path, backend_factory=lambda shard, hp, steps: backend, signature="fake",
                   clock=lambda: NOW, **kw), backend


def test_smoke_run_completes_and_returns_a_verified_final_artifact(tmp_path):
    resp, _ = run(tmp_path, request())
    assert resp.status == "final" and resp.step == resp.total_steps == 3 and resp.checkpoint_id.startswith("qwen-lora-")
    manifest = load_manifest(tmp_path / "run-smoke" / "final" / "artifact_manifest.json")
    assert manifest.model_dump(mode="json") == resp.manifest
    assert manifest.data_source_model_version == "unspecified-source-model" or manifest.data_source_model_version
    assert manifest.cost_usd is not None and "estimate" in manifest.cost_basis  # list rates x measured seconds, labelled
    assert (tmp_path / "run-smoke" / "dataset.jsonl").exists()


def test_pause_then_resume_through_the_service_and_idempotent_rerun(tmp_path):
    first, _ = run(tmp_path, request(stop_after_steps=1))
    assert first.status == "paused" and first.manifest is None and first.checkpoint_id is None
    second, backend = run(tmp_path, request())
    assert second.status == "final" and second.resumed_from_step == 1 and len(backend.seen) == 2
    third, backend3 = run(tmp_path, request())
    assert third.manifest == second.manifest and backend3.seen == []


def test_container_rechecks_pins_gpu_manifest_and_ceiling_even_if_caller_lied(tmp_path):
    req = request()
    bad_plan = req.plan.model_copy(update={"base_revision": "a" * 40})
    with pytest.raises(GateError) as err:
        run(tmp_path, req.model_copy(update={"plan": bad_plan}))
    assert err.value.code == "unpinned_model"
    with pytest.raises(GateError) as err:
        run(tmp_path, req.model_copy(update={"plan": req.plan.model_copy(update={"gpu": "H100"})}))
    assert err.value.code == "unsupported_gpu"
    other = req.approval.model_copy(update={"manifest_hash": "0" * 64})
    with pytest.raises(GateError) as err:
        run(tmp_path, req.model_copy(update={"approval": other}))
    assert err.value.code == "approved_manifest_mismatch"
    inflated = req.approval.model_copy(update={"budget_seconds": 100_000.0})
    with pytest.raises(GateError) as err:
        run(tmp_path, req.model_copy(update={"approval": inflated}))
    assert err.value.code == "budget_exceeds_ceiling"
    assert not (tmp_path / "run-smoke").exists()  # nothing was created before verification passed


def test_tampered_shard_or_wrong_dataset_hash_is_rejected_before_any_training(tmp_path):
    req = request()
    with pytest.raises(ShardError) as err:
        run(tmp_path, req.model_copy(update={"shard": req.shard + " "}))
    assert err.value.code == "dataset_hash_mismatch"
    with pytest.raises(GateError) as err:
        run(tmp_path, req.model_copy(update={"plan": req.plan.model_copy(update={"record_count": 99})}))
    assert err.value.code in {"record_count_mismatch", "approved_manifest_mismatch"}


def test_same_run_id_with_different_plan_is_refused_not_resumed(tmp_path):
    run(tmp_path, request(stop_after_steps=1))
    changed = request()
    plan = changed.plan.model_copy(update={"hyperparameters": HP.model_copy(update={"learning_rate": Decimal("0.001")})})
    with pytest.raises(ResumeError) as err:
        run(tmp_path, changed.model_copy(update={"plan": plan}))
    assert err.value.code == "incompatible_run"
