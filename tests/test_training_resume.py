import datetime as dt
import shutil

import pytest

from training.resume import CheckpointStore, ResumeError, RunIdentity

BASE = dict(run_id="run-0001", plan_hash="a" * 64, base_model="Qwen/Qwen2.5-7B-Instruct", base_revision="b" * 40,
            training_manifest_hash="c" * 64, dataset_hash="d" * 64, hyperparameters={"epochs": 1, "seed": 7},
            backend_signature="torch==2.6.0")


def identity(**over):
    return RunIdentity(**{**BASE, **over})


class FileBackend:
    """Writes whatever 'state' it holds; enough to exercise the store without torch."""
    def __init__(self, state="s0"):
        self.state = state

    def capture(self, directory):
        (directory / "adapter").mkdir()
        (directory / "adapter" / "adapter_model.safetensors").write_text(self.state)
        (directory / "trainer_state.pt").write_text("opt:" + self.state)

    def restore(self, directory):
        self.state = (directory / "adapter" / "adapter_model.safetensors").read_text()


def store(tmp_path, **over):
    s = CheckpointStore(tmp_path, identity(**over), clock=lambda: dt.datetime(2026, 11, 1, tzinfo=dt.timezone.utc))
    s.init_run()
    return s


def save(s, step, state="s"):
    return s.save(step=step, epoch=0, index_in_epoch=step, loss_history=tuple(1.0 / i for i in range(1, step + 1)),
                  backend=FileBackend(f"{state}{step}"))


def test_fresh_run_has_no_checkpoint_and_save_is_atomic_and_verifiable(tmp_path):
    s = store(tmp_path)
    assert s.latest_valid() is None
    meta = save(s, 3)
    found, directory = s.latest_valid()
    assert found == meta and directory.name == "step-000003"
    assert set(meta.files) == {"adapter/adapter_model.safetensors", "trainer_state.pt"}
    assert not list(s.checkpoints_dir.glob(".tmp-*"))
    assert s.read_ledger().lineage[0].step == 3


def test_resume_picks_newest_and_restores_backend_state(tmp_path):
    s = store(tmp_path)
    save(s, 2)
    save(s, 4)
    meta, directory = s.latest_valid()
    backend = FileBackend()
    backend.restore(directory)
    assert meta.step == 4 and backend.state == "s4" and meta.index_in_epoch == 4 and len(meta.loss_history) == 4


def test_corrupt_latest_is_skipped_and_recorded_not_used(tmp_path):
    s = store(tmp_path)
    save(s, 2)
    save(s, 4)
    (s.checkpoints_dir / "step-000004" / "trainer_state.pt").write_text("bitrot")
    meta, _ = s.latest_valid()
    assert meta.step == 2 and s.read_ledger().skipped_corrupt == ("step-000004",)


def test_missing_meta_and_truncated_files_are_corrupt(tmp_path):
    s = store(tmp_path)
    save(s, 2)
    save(s, 4)
    (s.checkpoints_dir / "step-000004" / "meta.json").unlink()
    assert s.latest_valid()[0].step == 2
    shutil.rmtree(s.checkpoints_dir / "step-000002" / "adapter")
    with pytest.raises(ResumeError) as err:
        s.latest_valid()
    assert err.value.code == "no_valid_checkpoint"  # never silently restart from scratch


def test_second_launch_with_different_identity_is_refused(tmp_path):
    store(tmp_path)
    for field, value in (("base_revision", "e" * 40), ("base_model", "other/model"), ("dataset_hash", "e" * 64),
                         ("training_manifest_hash", "e" * 64), ("hyperparameters", {"epochs": 2, "seed": 7}),
                         ("backend_signature", "torch==2.7.0"), ("plan_hash", "e" * 64)):
        with pytest.raises(ResumeError) as err:
            store(tmp_path, **{field: value})
        assert err.value.code == "incompatible_run" and field in str(err.value)


def test_same_identity_relaunch_is_idempotent(tmp_path):
    s = store(tmp_path)
    save(s, 2)
    again = store(tmp_path)
    assert again.latest_valid()[0].step == 2 and again.read_ledger().lineage[0].step == 2


def test_checkpoint_from_another_identity_is_incompatible_not_corrupt(tmp_path):
    s = store(tmp_path)
    save(s, 2)
    meta_path = s.checkpoints_dir / "step-000002" / "meta.json"
    foreign = meta_path.read_text().replace(s.identity.identity_hash, "9" * 64)
    meta_path.write_text(foreign)
    with pytest.raises(ResumeError) as err:
        s.latest_valid()
    assert err.value.code == "incompatible_checkpoint"


def test_saving_the_same_step_twice_is_idempotent(tmp_path):
    s = store(tmp_path)
    first = save(s, 2)
    assert save(s, 2, state="different") == first
    assert len(s.read_ledger().lineage) == 1


def test_crashed_save_leaves_only_a_temp_dir_that_prune_removes(tmp_path):
    s = store(tmp_path)

    class Crash(FileBackend):
        def capture(self, directory):
            super().capture(directory)
            raise RuntimeError("killed mid-capture")

    with pytest.raises(RuntimeError):
        s.save(step=2, epoch=0, index_in_epoch=2, loss_history=(1.0, 1.0), backend=Crash())
    assert s.latest_valid() is None and not list(s.checkpoints_dir.glob("step-*"))
    (s.checkpoints_dir / ".tmp-000009-dead").mkdir()
    s.prune()
    assert not list(s.checkpoints_dir.glob(".tmp-*"))


def test_prune_keeps_newest_two_payloads_but_lineage_survives(tmp_path):
    s = store(tmp_path)
    for step in (1, 2, 3, 4):
        save(s, step)
    s.prune(keep=2)
    assert [p.name for p in sorted(s.checkpoints_dir.iterdir())] == ["step-000003", "step-000004"]
    assert [e.step for e in s.read_ledger().lineage] == [1, 2, 3, 4]


def test_unclosed_launch_is_charged_wall_clock_capped_at_its_budget_and_closed_at_the_resumed_step(tmp_path):
    s = store(tmp_path)
    i = s.begin_launch(budget_seconds=100, start_step=0)
    s.record_progress(i, end_step=4, duration_seconds=30)  # then the container is killed: never closed
    start = dt.datetime(2026, 11, 1, tzinfo=dt.timezone.utc)
    ledger = s.read_ledger()
    assert ledger.consumed_seconds_upper_bound(start) == 30                                    # nothing known beyond progress
    assert ledger.consumed_seconds_upper_bound(start + dt.timedelta(seconds=70)) == 70          # wall clock since start
    assert ledger.consumed_seconds_upper_bound(start + dt.timedelta(hours=9)) == 100            # never more than the allowance
    j = s.begin_launch(budget_seconds=50, start_step=2)     # resumed from an older (corrupt-fallback) checkpoint
    ledger = s.read_ledger()
    assert ledger.launches[0].closed and ledger.launches[0].end_step == 2 and ledger.launches[0].duration_seconds == 30
    s.record_progress(j, end_step=6, duration_seconds=20, close=True)
    assert s.read_ledger().consumed_seconds_upper_bound(start) == 50
