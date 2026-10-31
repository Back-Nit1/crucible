import os
import threading
from decimal import Decimal

import pytest

from memory.checkpoints import CheckpointConflict, CheckpointCorrupt, CheckpointStore
from world.evolution import GenerationCheckpoint, initialize_population


def cp(tasks=("t1", "t2", "t3"), size=2):
    return GenerationCheckpoint(generation_id="gen-0", seed=1, genomes=initialize_population(size, 1), task_ids=tasks)


def test_create_is_idempotent_and_conflicting_identity_is_refused(tmp_path):
    s = CheckpointStore(tmp_path)
    a = s.create(cp())
    assert s.create(cp()) == a
    with pytest.raises(CheckpointConflict):
        s.create(cp(tasks=("other",)))


def test_resume_schedules_only_remaining_pairs_and_never_duplicates(tmp_path):
    s = CheckpointStore(tmp_path)
    c = s.create(cp())
    keys = c.remaining_episode_keys()
    assert len(keys) == 6
    for k in keys[:4]:
        s.complete("gen-0", k, {"fitness": "0.5"})
    s.complete("gen-0", keys[0], {"fitness": "0.9"})  # replay of a finished pair
    fresh = CheckpointStore(tmp_path)  # a new process resuming from disk
    assert fresh.remaining("gen-0") == keys[4:]
    assert list(fresh.load("gen-0").completed_episode_keys) == list(keys[:4])
    assert fresh.results("gen-0")[keys[0]] == {"fitness": "0.5"}  # replay did not overwrite


def test_unknown_pair_is_rejected(tmp_path):
    s = CheckpointStore(tmp_path)
    s.create(cp())
    with pytest.raises(ValueError):
        s.complete("gen-0", "nope:t1", {})


def test_crash_during_write_leaves_the_previous_checkpoint_intact(tmp_path, monkeypatch):
    s = CheckpointStore(tmp_path)
    c = s.create(cp())
    k = c.remaining_episode_keys()
    s.complete("gen-0", k[0], {})
    monkeypatch.setattr(os, "replace", lambda *a: (_ for _ in ()).throw(OSError("disk gone")))
    with pytest.raises(OSError):
        s.complete("gen-0", k[1], {})
    monkeypatch.undo()
    assert list(CheckpointStore(tmp_path).load("gen-0").completed_episode_keys) == [k[0]]
    assert not list(tmp_path.glob("*.tmp"))  # no torn temp files left behind


def test_corruption_is_detected_not_resumed(tmp_path):
    s = CheckpointStore(tmp_path)
    s.create(cp())
    p = tmp_path / "gen-0.json"
    p.write_text(p.read_text().replace('"seed": 1', '"seed": 2', 1))
    with pytest.raises(CheckpointCorrupt):
        s.load("gen-0")


def test_concurrent_workers_record_distinct_pairs_without_loss(tmp_path):
    s = CheckpointStore(tmp_path)
    keys = s.create(cp(tasks=tuple(f"t{i}" for i in range(6)))).remaining_episode_keys()
    ts = [threading.Thread(target=lambda k=k: s.complete("gen-0", k, {"k": k})) for k in keys]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert sorted(s.load("gen-0").completed_episode_keys) == sorted(keys) and s.remaining("gen-0") == ()


def test_finalize_requires_all_pairs_and_commit_hook_runs(tmp_path):
    commits = []
    s = CheckpointStore(tmp_path, commit=lambda: commits.append(1))
    c = s.create(cp(tasks=("t1",)))
    with pytest.raises(ValueError):
        s.finalize("gen-0", {}, ())
    for k in c.remaining_episode_keys():
        s.complete("gen-0", k, {})
    g = c.genomes[0].id
    done = s.finalize("gen-0", {g: Decimal("0.7")}, (c.genomes[1].id,))
    assert done.status == "complete" and done.fitness[g] == Decimal("0.7") and commits
    with pytest.raises(ValueError):
        s.complete("gen-0", "x", {})
