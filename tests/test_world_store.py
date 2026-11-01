import json
from decimal import Decimal as D

import pytest

from world.evolution import GenerationCheckpoint, initialize_population
from world.store import (Compat, CorruptCheckpoint, EpisodeOutcome, FileBlobStore, GenerationLocked,
                         GenerationState, GenerationStatus, GenerationStore, IncompatibleCheckpoint,
                         MemoryBlobStore, decode, encode)

GENOMES = initialize_population(3, 9)
TASKS = ("t1", "t2")
COMPAT = Compat(task_set_hash="tasks-v1", catalog_hash="cat-1", rules_version="K001:1", population_hash="pop-1")


def fresh(compat=COMPAT, genomes=GENOMES, tasks=TASKS):
    return GenerationState(compat=compat, checkpoint=GenerationCheckpoint(
        generation_id="g1", seed=7, genomes=genomes, task_ids=tasks))


def out(i, fit="0.5", killed=False):
    return EpisodeOutcome(episode_id=f"ep-{i}", fitness=D(fit), killed=killed, termination="success")


@pytest.fixture(params=["memory", "file"])
def store(request, tmp_path):
    return GenerationStore(MemoryBlobStore() if request.param == "memory" else FileBlobStore(tmp_path))


def test_resume_schedules_only_remaining_pairs_and_never_repeats_completed(store):
    s = store.start_or_resume("g1", fresh())
    first = s.remaining()[0]
    store.record_episode("g1", first, out(1))
    resumed = store.start_or_resume("g1", fresh())  # simulated restart
    assert first not in resumed.remaining() and len(resumed.remaining()) == 5
    again = store.record_episode("g1", first, out(2, "0.9"))  # replayed completion: no duplicate, original kept
    assert again.checkpoint.completed_episode_keys.count(first) == 1 and again.outcomes[first].episode_id == "ep-1"


def test_status_lifecycle_and_deterministic_summary(store):
    store.start_or_resume("g1", fresh())
    assert store.load("g1").status is GenerationStatus.PENDING
    for status in (GenerationStatus.RUNNING, GenerationStatus.INTERRUPTED, GenerationStatus.RUNNING):
        assert store.set_status("g1", status).status is status
    for i, key in enumerate(store.load("g1").remaining()):
        store.record_episode("g1", key, out(i, fit="0.8" if GENOMES[0].id in key else "0.4", killed=GENOMES[2].id in key and key.endswith("t1")))
    done = store.finalize("g1")
    assert done.status is GenerationStatus.COMPLETED and done.checkpoint.status == "complete"
    assert done.summary.killed_ids == (GENOMES[2].id,) and GENOMES[2].id not in done.summary.survivor_ids
    assert done.summary.best_fitness == D("0.800000") and done.checkpoint.fitness[GENOMES[0].id] == D("0.800000")
    assert store.finalize("g1") == done  # idempotent
    assert store.start_or_resume("g1", fresh()).status is GenerationStatus.COMPLETED  # completed gen is not rerun


def test_finalize_refuses_incomplete_generation(store):
    store.start_or_resume("g1", fresh())
    with pytest.raises(ValueError):
        store.finalize("g1")


def test_incompatible_versions_are_rejected(store):
    store.start_or_resume("g1", fresh())
    for field in ("task_set_hash", "catalog_hash", "rules_version", "population_hash"):
        with pytest.raises(IncompatibleCheckpoint):
            store.start_or_resume("g1", fresh(compat=COMPAT.model_copy(update={field: "other"})))
    with pytest.raises(IncompatibleCheckpoint):
        store.start_or_resume("g1", fresh(tasks=("t1", "t3")))
    with pytest.raises(IncompatibleCheckpoint):
        store.start_or_resume("g1", fresh(genomes=initialize_population(3, 10)))


def test_corrupted_checkpoints_are_rejected(store):
    blobs = store.blobs
    store.start_or_resume("g1", fresh())
    good = blobs.read("gen-g1.json")
    doc = json.loads(good)
    tampered = json.loads(good); tampered["body"]["checkpoint"]["seed"] = 8
    bad_version = {**doc, "version": 99}
    for raw in (b"", b"{not json", good[: len(good) // 2], json.dumps(tampered).encode(), json.dumps(bad_version).encode(),
                json.dumps({"version": 1, "content_hash": "x", "body": {}}).encode()):
        blobs.write("gen-g1.json", raw)
        with pytest.raises(CorruptCheckpoint):
            store.start_or_resume("g1", fresh())
    with pytest.raises(CorruptCheckpoint):
        decode(b"[]")


def test_hash_covers_content_so_encode_is_deterministic():
    assert encode(fresh()) == encode(fresh())


def test_file_write_is_atomic_when_the_new_state_cannot_be_written(tmp_path, monkeypatch):
    store = GenerationStore(FileBlobStore(tmp_path))
    store.start_or_resume("g1", fresh())
    before = (tmp_path / "gen-g1.json").read_bytes()
    monkeypatch.setattr("os.replace", lambda *a: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        store.record_episode("g1", store.load("g1").remaining()[0], out(1))
    monkeypatch.undo()
    assert (tmp_path / "gen-g1.json").read_bytes() == before  # committed state untouched
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".tmp-")]  # temp file cleaned up
    assert store.load("g1").remaining() == fresh().remaining()


def test_volume_hooks_run_on_write_and_before_read(tmp_path):
    calls = []
    store = GenerationStore(FileBlobStore(tmp_path, after_write=lambda: calls.append("commit"), before_read=lambda: calls.append("reload")))
    store.start_or_resume("g1", fresh())
    assert calls[:2] == ["reload", "commit"]


def test_single_writer_lease(store):
    store.acquire("g1", "runner-a")
    with pytest.raises(GenerationLocked, match="runner-a"):
        store.acquire("g1", "runner-b")
    store.release("g1")
    store.acquire("g1", "runner-b")


def test_stale_lease_is_taken_over_but_a_live_one_is_not(store):
    import datetime as dt
    t0 = dt.datetime(2026, 11, 1, tzinfo=dt.UTC)
    store.acquire("g1", "runner-a", now=t0)
    with pytest.raises(GenerationLocked):
        store.acquire("g1", "runner-b", now=t0 + dt.timedelta(minutes=29))
    store.acquire("g1", "runner-b", now=t0 + dt.timedelta(minutes=31))  # runner-a was preempted
    with pytest.raises(GenerationLocked, match="runner-b"):
        store.acquire("g1", "runner-c", now=t0 + dt.timedelta(minutes=32))
