import datetime as dt
import json
import random
from collections.abc import Sequence

import pytest

from modal_app.adapter_artifact import ADAPTER_CONFIG, ADAPTER_WEIGHTS, MANIFEST_FILENAME, verify_adapter_dir
from training.planning import LoRAHyperparameters, ResourceRates
from training.resume import CheckpointStore, ResumeError, RunIdentity
from training.trainer import batch_indices, position, run_training

N = 10  # dataset rows
HP = LoRAHyperparameters(epochs=2, micro_batch_size=1, gradient_accumulation_steps=3, checkpoint_every_steps=2, seed=11)
# 10 rows / 3 per step -> 4 steps per epoch, 8 total
NOW = dt.datetime(2026, 11, 1, tzinfo=dt.timezone.utc)


def identity(**over):
    base = dict(run_id="run-0001", plan_hash="a" * 64, base_model="Qwen/Qwen2.5-7B-Instruct", base_revision="b" * 40,
                training_manifest_hash="c" * 64, dataset_hash="d" * 64, hyperparameters=HP.model_dump(mode="json"),
                backend_signature="fake")
    return RunIdentity(**{**base, **over})


class StatefulBackend:
    """Weights + momentum ('optimizer') + a dropout RNG + a step counter. Any state NOT restored on resume changes the
    final weights, which is exactly what makes the equivalence test meaningful."""
    def __init__(self, restore_optimizer=True, restore_rng=True):
        self.w, self.m, self.rng, self.seen = [0.0, 0.0], [0.0, 0.0], random.Random(5), []
        self.restore_optimizer, self.restore_rng = restore_optimizer, restore_rng

    def train_step(self, example_indices: Sequence[int]) -> float:
        self.seen.append(tuple(example_indices))
        grad = [sum(example_indices) / 10 + self.rng.random() * 0.01, len(example_indices) * 0.1]
        self.m = [0.9 * m + g for m, g in zip(self.m, grad)]
        self.w = [w - 0.01 * m for w, m in zip(self.w, self.m)]
        return sum(abs(x) for x in self.w)

    def capture(self, directory):
        (directory / "adapter_model.safetensors").write_text(json.dumps(self.w))
        (directory / "optimizer.json").write_text(json.dumps(self.m))
        (directory / "rng.json").write_text(json.dumps(self.rng.getstate()))

    def restore(self, directory):
        self.w = json.loads((directory / "adapter_model.safetensors").read_text())
        if self.restore_optimizer:
            self.m = json.loads((directory / "optimizer.json").read_text())
        if self.restore_rng:
            v, st, g = json.loads((directory / "rng.json").read_text())
            self.rng.setstate((v, tuple(st), g))

    def export_adapter(self, directory):
        (directory / ADAPTER_CONFIG).write_text('{"peft_type": "LORA"}')
        (directory / ADAPTER_WEIGHTS).write_text(json.dumps(self.w))


def make_store(tmp_path, **over):
    return CheckpointStore(tmp_path, identity(**over), clock=lambda: NOW)


def go(tmp_path, backend=None, **kw):
    backend = backend or StatefulBackend()
    store = make_store(tmp_path)
    out = run_training(store=store, identity=store.identity, backend=backend, hp=HP, record_count=N,
                       total_budget_seconds=kw.pop("budget", 1000), gpu="L4", clock=lambda: NOW, **kw)
    return out, backend, store


def test_schedule_is_deterministic_covers_every_row_each_epoch_and_position_is_derived():
    epoch0 = [i for s in range(4) for i in batch_indices(s, HP, N)]
    epoch1 = [i for s in range(4, 8) for i in batch_indices(s, HP, N)]
    assert sorted(epoch0) == sorted(epoch1) == list(range(N)) and epoch0 != epoch1
    assert batch_indices(5, HP, N) == batch_indices(5, HP, N)
    assert (position(0, HP, N), position(3, HP, N), position(4, HP, N), position(8, HP, N)) == ((0, 0), (0, 3), (1, 0), (2, 0))


def test_uninterrupted_run_finalizes_with_a_verified_artifact(tmp_path):
    out, backend, store = go(tmp_path)
    assert out.status == "final" and out.step == out.total_steps == 8 and out.resumed_from_step == 0
    m = out.manifest
    assert m.steps_completed == m.total_steps == 8 and m.epochs_completed == 2 and m.cost_usd is None
    assert m.checkpoint_lineage[-1].step == 8 and m.segments[0].start_step == 0
    verify_adapter_dir(m, store.final_dir)
    assert (store.final_dir / MANIFEST_FILENAME).exists()


def test_interrupt_and_resume_equals_uninterrupted_run_exactly(tmp_path):
    whole, whole_backend, _ = go(tmp_path / "whole")
    first, b1, store = go(tmp_path / "split", stop_after_steps=3)
    assert first.status == "paused" and first.step == 3 and first.manifest is None
    assert not store.final_dir.exists()  # an incomplete run is never final
    second, b2, store2 = go(tmp_path / "split", backend=StatefulBackend())  # brand-new process, brand-new backend object
    assert second.status == "final" and second.resumed_from_step == 3
    assert b2.seen == whole_backend.seen[3:]  # sampler continued from the right place
    assert second.losses == whole.losses
    assert second.manifest.adapter_hash == whole.manifest.adapter_hash
    assert [s.start_step for s in second.manifest.segments] == [0, 3]
    assert second.manifest.training_manifest_hash == whole.manifest.training_manifest_hash


@pytest.mark.parametrize("kw", [{"restore_optimizer": False}, {"restore_rng": False}])
def test_resume_without_optimizer_or_rng_state_would_diverge(tmp_path, kw):
    """Proves the equivalence test above has teeth: 'restart from weights' is not resume."""
    whole, _, _ = go(tmp_path / "whole")
    go(tmp_path / "split", stop_after_steps=3)
    second, _, _ = go(tmp_path / "split", backend=StatefulBackend(**kw))
    assert second.manifest.adapter_hash != whole.manifest.adapter_hash


def test_hard_kill_between_checkpoints_resumes_from_the_last_durable_step(tmp_path):
    class Dies(StatefulBackend):
        def train_step(self, idx):
            if len(self.seen) == 5:  # dies during step 6; checkpoints exist at 2 and 4
                raise RuntimeError("container killed")
            return super().train_step(idx)

    store = make_store(tmp_path)
    with pytest.raises(RuntimeError):
        run_training(store=store, identity=store.identity, backend=Dies(), hp=HP, record_count=N,
                     total_budget_seconds=1000, gpu="L4", clock=lambda: NOW)
    assert store.read_ledger().launches[0].closed is False and store.latest_valid()[0].step == 4
    out, _, _ = go(tmp_path)
    assert out.status == "final" and out.resumed_from_step == 4
    whole, _, _ = go(tmp_path / "ref")
    assert out.manifest.adapter_hash == whole.manifest.adapter_hash


def test_finished_run_is_idempotent_and_executes_no_steps(tmp_path):
    first, _, _ = go(tmp_path)
    again, backend, _ = go(tmp_path)
    assert again.status == "final" and backend.seen == [] and again.manifest == first.manifest


def test_changed_base_revision_or_data_refuses_to_resume(tmp_path):
    go(tmp_path, stop_after_steps=3)
    for over in ({"base_revision": "e" * 40}, {"dataset_hash": "e" * 64}, {"training_manifest_hash": "e" * 64}):
        store = make_store(tmp_path, **over)
        with pytest.raises(ResumeError) as err:
            run_training(store=store, identity=store.identity, backend=StatefulBackend(), hp=HP, record_count=N,
                         total_budget_seconds=1000, gpu="L4")
        assert err.value.code == "incompatible_run"


def test_wall_clock_budget_pauses_with_a_checkpoint_and_exhausted_budget_refuses(tmp_path):
    ticks = iter(range(0, 1000, 10))
    out, _, store = go(tmp_path, budget=25, monotonic=lambda: float(next(ticks)))
    assert out.status == "paused" and out.manifest is None and store.latest_valid()[0].step == out.step
    ledger = store.read_ledger()
    assert ledger.status == "paused" and ledger.launches[0].closed
    with pytest.raises(ResumeError) as err:
        go(tmp_path, budget=ledger.consumed_seconds_upper_bound(NOW))
    assert err.value.code == "budget_exhausted"


def test_cost_is_known_only_when_rates_are_supplied_and_is_measured_not_estimated(tmp_path):
    rates = ResourceRates(gpu_per_second="0.001", cpu_cores="2", cpu_per_core_second="0.0001", memory_gib="32",
                          memory_per_gib_second="0.00001", source="modal list rates", as_of="2026-11-01")
    ticks = iter(float(i) for i in range(100))
    out, _, _ = go(tmp_path, rates=rates, monotonic=lambda: next(ticks))
    m = out.manifest
    assert m.cost_usd is not None and "modal list rates" in m.cost_basis
    assert float(m.cost_usd) == pytest.approx(m.duration_seconds * (0.001 + 2 * 0.0001 + 32 * 0.00001))


def test_corrupt_checkpoint_on_resume_falls_back_and_still_matches(tmp_path):
    go(tmp_path / "s", stop_after_steps=5)  # checkpoints at 2,4 and the pause save at 5
    store = make_store(tmp_path / "s")
    (store.checkpoints_dir / "step-000005" / "optimizer.json").write_text("garbage")
    out, _, _ = go(tmp_path / "s")
    whole, _, _ = go(tmp_path / "w")
    assert out.resumed_from_step == 4 and out.manifest.adapter_hash == whole.manifest.adapter_hash
    assert store.read_ledger().skipped_corrupt == ("step-000005",)
