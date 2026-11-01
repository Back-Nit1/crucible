from memory import InMemoryTraceRepository
from scripts.audit_traces import audit
from tests.fixtures.frozen import HASHES, SyntheticFrozen
from world.runtime import build_population, run_generation
from world.store import GenerationStore, MemoryBlobStore
from world.taskgen import generate_tasks


def test_audit_flags_missing_and_duplicate_traces_and_passes_a_clean_generation():
    cat = SyntheticFrozen()
    traces, store = InMemoryTraceRepository(), GenerationStore(MemoryBlobStore())
    res = run_generation(generation_id="g", seed=1, genomes=build_population(4, 1, fixtures=False),
                         tasks=generate_tasks(cat, HASHES, seed=1, count=4, review_traps=0), manifests=HASHES, catalog=cat,
                         store=store, traces=traces)
    assert audit(res.state, traces.traces)["ok"]
    assert not audit(res.state, traces.traces[1:])["ok"] and audit(res.state, traces.traces[1:])["missing"] == 1
    bad = audit(res.state, [*traces.traces, traces.traces[0]])
    assert not bad["ok"] and bad["duplicates"] == 1
