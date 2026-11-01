from world.evolution import GenerationCheckpoint, initialize_population
from world.remote import approx_cost_usd, latest_unfinished, status
from world.store import Compat, GenerationState, GenerationStatus, GenerationStore, MemoryBlobStore

C = Compat(task_set_hash="t", catalog_hash="c", rules_version="r", population_hash="p")


def put(store, gid, status_):
    st = GenerationState(compat=C, status=status_, checkpoint=GenerationCheckpoint(
        generation_id=gid, seed=1, genomes=initialize_population(2, 1), task_ids=("t",)))
    store.save(gid, st)


def test_status_lists_every_generation_and_flags_corruption_and_scheduler_resumes_only_unfinished():
    store = GenerationStore(MemoryBlobStore())
    put(store, "a", GenerationStatus.COMPLETED); put(store, "b", GenerationStatus.INTERRUPTED); put(store, "c", GenerationStatus.FAILED)
    store.blobs.write("gen-d.json", b"garbage")
    s = {r["generation_id"]: r for r in status(store)}
    assert s["a"]["status"] == "completed" and s["b"]["episodes"] == "0/2" and s["d"]["status"] == "corrupt"
    assert latest_unfinished(store) == "b"  # failed/completed/corrupt are never auto-resumed
    put(store, "b", GenerationStatus.COMPLETED)
    assert latest_unfinished(store) is None


def test_cost_is_wall_time_times_list_price():
    c = approx_cost_usd(3600)
    assert c["gpu_usd"] == 0 and 0.05 < c["total_usd"] < 0.06  # ~$0.055 per CPU-hour at 1 core / 1 GiB
