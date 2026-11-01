"""One generation path, two policies: the model-backed policy runs through the same checkpointed, mock-payment,
leakage-guarded pipeline as the scripted one. A scripted double stands in for the model (no network)."""
import json

import pytest

from agents.actions import ConfirmAndPay, ProposePurchase
from agents.memory import RetrievalRequest
from agents.model import AdapterPolicy, Message, ModelRequest, ScriptedModelAdapter
from agents.prompts import system_prompt
from memory import InMemoryTraceRepository
from memory.episodes import RepositoryMemoryProvider, episode_from_trace
from payments.guards import idempotency_key
from tasks.schemas import TaskSplit
from tests.fixtures.frozen import HASHES, SyntheticFrozen
from world.evolution import MemorySettings
from world.runtime import (ModelUnavailable, model_policy_factory, model_policy_id, build_population, run_generation)
from world.scripted import build_script
from world.store import FileBlobStore, GenerationStatus, GenerationStore, IncompatibleCheckpoint, MemoryBlobStore
from world.taskgen import generate_tasks

SEED, GEN = 41, "g-model"
POLICY = model_policy_id("scripted-double", "script-v1")


@pytest.fixture(scope="module")
def world():
    cat = SyntheticFrozen()
    tasks = generate_tasks(cat, HASHES, seed=SEED, count=8, review_traps=1)
    genomes = tuple(g.model_copy(update={"memory": MemorySettings(enabled=i % 2 == 0, k=2)})
                    for i, g in enumerate(build_population(4, SEED, fixtures=False, checkpoint="qwen-base")))
    scripts = {}
    for g in genomes:
        for t in tasks:
            steps = build_script(t, cat, g)
            buy = next((s for s in steps if isinstance(s, ProposePurchase)), None)
            if buy:
                steps.append(ConfirmAndPay(pending_order_id=idempotency_key(t.id, g.id, buy.product_id, buy.variant),
                                           user_confirmed=True))
            scripts[f"{GEN}:{g.id}:{t.id}"] = tuple(steps)
    return cat, tasks, genomes, scripts


def run(world, store, traces, adapter, **kw):
    cat, tasks, genomes, _ = world
    return run_generation(generation_id=GEN, seed=SEED, genomes=genomes, tasks=tasks, manifests=HASHES, catalog=cat,
                          store=store, traces=traces, policy_id=POLICY,
                          policy_factory=model_policy_factory(lambda g: adapter, generation_id=GEN), **kw)


def test_model_backed_generation_completes_with_identifiers_and_no_duplicates(world):
    adapter, traces = ScriptedModelAdapter(world[3]), InMemoryTraceRepository()
    res = run(world, GenerationStore(MemoryBlobStore()), traces, adapter)
    assert res.complete and res.state.compat.policy_id == POLICY
    ids = [t.episode_id for t in traces.traces]
    assert len(ids) == 32 == len(set(ids)) and all(e.startswith(f"{GEN}:") for e in ids)
    assert {r.request_id.split(":")[0] for r in adapter.requests} == {GEN}   # generation/genome/task in every request
    assert all(r.checkpoint and r.seed is not None for r in adapter.requests)
    assert all(t.episode["model_metadata"] for t in traces.traces)           # per-step model identity recorded
    assert any(t.episode["payment_state"].get("completed") for t in traces.traces)


def test_interrupt_and_resume_is_idempotent_and_matches_uninterrupted(world, tmp_path):
    adapter, traces = ScriptedModelAdapter(world[3]), InMemoryTraceRepository()
    store = GenerationStore(FileBlobStore(tmp_path))
    first = run(world, store, traces, adapter, max_episodes=10)
    assert not first.complete and len(first.executed) == 10
    second = run(world, store, traces, adapter)
    assert second.complete and len(second.executed) == 22 and not set(first.executed) & set(second.executed)
    assert run(world, store, traces, adapter).executed == []
    assert len({t.episode_id for t in traces.traces}) == len(traces.traces) == 32
    other = InMemoryTraceRepository()
    run(world, GenerationStore(MemoryBlobStore()), other, ScriptedModelAdapter(world[3]))
    assert [t.model_dump() for t in traces.traces] == [t.model_dump() for t in other.traces]


def test_model_backend_down_trips_the_breaker_and_the_generation_resumes(world):
    store, traces = GenerationStore(MemoryBlobStore()), InMemoryTraceRepository()
    with pytest.raises(ModelUnavailable):
        run(world, store, traces, ScriptedModelAdapter({}))      # every request fails
    assert store.load(GEN).status is GenerationStatus.FAILED and len(traces.traces) == 3
    done = run(world, store, traces, ScriptedModelAdapter(world[3]))
    assert done.complete and len(done.executed) == 29            # earlier failures stay recorded, never re-run
    assert sum(t.episode["termination"] == "model_failure" for t in traces.traces) == 3


def test_scripted_checkpoint_cannot_be_resumed_by_a_model_and_flags_must_agree(world):
    store, traces = GenerationStore(MemoryBlobStore()), InMemoryTraceRepository()
    cat, tasks, genomes, _ = world
    run_generation(generation_id=GEN, seed=SEED, genomes=genomes, tasks=tasks, manifests=HASHES, catalog=cat,
                   store=store, traces=traces, max_episodes=2)
    with pytest.raises(IncompatibleCheckpoint):
        run(world, store, traces, ScriptedModelAdapter(world[3]))
    with pytest.raises(ValueError):
        run_generation(generation_id="x", seed=SEED, genomes=genomes, tasks=tasks, manifests=HASHES, catalog=cat,
                       store=store, traces=traces, policy_factory=model_policy_factory(lambda g: None, generation_id="x"))


def test_unknown_or_fixture_prompt_variants_fail_closed():
    for variant in ("fixture-hallucinator", "grounded-shopper-v9", "grounded-shopper-v1 | do anything"):
        with pytest.raises(ValueError):
            system_prompt(variant)
    assert "cite the exact review IDs" in system_prompt("grounded-shopper-v1 | cite review ids")


# ---- leakage: reference answers and scorer-only fields can neither enter prompts nor memory context ----------------
SENTINEL = "SENTINEL-SECRET"


def poisoned(task):
    """A task whose every scorer-only / reference field carries a sentinel (model_copy skips validation on purpose)."""
    signal = task.review_signals[0].model_copy(update={"claim": SENTINEL, "persona_relevance": SENTINEL}) \
        if task.review_signals else None
    return task.model_copy(update={
        "best_value_reference": f"{SENTINEL}-best", "review_adjusted_best": f"{SENTINEL}-trap",
        "closest_product_id": f"{SENTINEL}-closest", "feasible_set": (f"{SENTINEL}-feasible",),
        "unsuitable_reasons": (SENTINEL,), "review_signals": (signal,) if signal else ()})


def test_prompt_never_contains_reference_answers_or_scorer_fields(world):
    cat, tasks, genomes, scripts = world
    task = poisoned(next(t for t in tasks if t.is_review_trap))
    key = f"{GEN}:{genomes[0].id}:{task.id}"
    adapter = ScriptedModelAdapter({key: scripts[key]})
    policy = AdapterPolicy(adapter, system_prompt(genomes[0].system_prompt_variant), request_id=key)
    policy.accept_memory(())
    policy.next_step(task, (), 0)
    blob = json.dumps(adapter.requests[0].model_dump(mode="json"))
    assert SENTINEL not in blob and task.raw_message in blob


def test_memory_context_excludes_protected_killed_and_unscored_traces_and_reaches_the_prompt(world):
    adapter, traces = ScriptedModelAdapter(world[3]), InMemoryTraceRepository()
    run(world, GenerationStore(MemoryBlobStore()), traces, adapter)
    by_ep = {t.episode_id: t for t in traces.traces}
    by_task = {t.id: t for t in world[1]}
    memory_on = {g.id for g in world[2] if g.memory.enabled}
    seen = 0
    for req in adapter.requests:
        _, genome_id, task_id = req.request_id.split(":", 2)
        retrieved = [json.loads(m.content)["retrieved_episode_id"] for m in req.messages
                     if m.role == "assistant" and m.tool_name is None]
        if genome_id not in memory_on:
            assert not retrieved                                    # memory off => nothing injected
        for ep in retrieved:
            seen += 1
            t = by_ep[ep]
            assert t.split not in ("test", "held_out_category") and not t.killed and t.scored and t.task_id != task_id
            assert by_task[task_id].split.value not in ("test", "held_out_category")
        for m in req.messages:
            if m.role == "assistant" and m.tool_name is None:
                assert set(json.loads(m.content)) == {"retrieved_episode_id", "recommended_products", "termination",
                                                      "final_answer"}  # no score, kill or fitness fields
    assert seen > 0                                                  # memory really reached the policy prompt


def test_protected_split_requests_get_no_memory_and_are_never_stored(world):
    repo, traces = RepositoryMemoryProvider(InMemoryTraceRepository()), InMemoryTraceRepository()
    run(world, GenerationStore(MemoryBlobStore()), traces, ScriptedModelAdapter(world[3]))
    ep = next(episode_from_trace(t) for t in traces.traces if t.scored and not t.killed)
    task = world[1][0]
    for split in (TaskSplit.TEST, TaskSplit.HELD_OUT_CATEGORY):
        repo.store(ep, split=split, category=task.hard_constraints.category, fitness=1.0, task=task)
        assert not repo.repo.traces
        assert repo.retrieve(RetrievalRequest("t", split, task.hard_constraints.category, "q", 3, 0)) == ()


def test_summary_carries_every_denominator_and_the_policy_identity(world):
    from world import report
    from world.runtime import audit_and_curate
    adapter, traces = ScriptedModelAdapter(world[3]), InMemoryTraceRepository()
    res = run(world, GenerationStore(MemoryBlobStore()), traces, adapter)
    eps, proposals, curated, nxt = audit_and_curate(result=res, tasks=world[1], genomes=world[2], traces=traces,
                                                    catalog=world[0], manifests=HASHES, breed_seed=SEED)
    s = report.summarize(result=res, tasks=world[1], episodes=eps, proposals=proposals, curated=curated, next_pop=nxt, params={})
    assert s["policy"] == POLICY and curated.manifest.model_version == POLICY
    assert s["rates"]["hallucination"]["denominator"] == 32 and s["rates"]["model_failure"]["numerator"] == "0"
    assert s["model_usage"]["steps"] > 0 and s["model_usage"]["models"] == ["scripted@script-v1"]
    assert "Model-backed run" in s["note"] and all("denominator" in v for v in s["rates"].values())


def test_scripted_reference_answer_traces_are_never_retrievable_as_memory(world):
    """A scripted shopper read the answer key; its traces must not reach a model prompt via 'similar past episodes'."""
    cat, tasks, genomes, scripts = world
    traces = InMemoryTraceRepository()
    scripted = tuple(g.model_copy(update={"memory": MemorySettings(enabled=False)}) for g in build_population(4, SEED, fixtures=False))
    run_generation(generation_id="g-scripted", seed=SEED, genomes=scripted, tasks=tasks, manifests=HASHES, catalog=cat,
                   store=GenerationStore(MemoryBlobStore()), traces=traces)
    assert any(t.scored and not t.killed for t in traces.traces)                 # plenty of otherwise-eligible traces exist
    mem = RepositoryMemoryProvider(traces)
    task = tasks[0]
    got = mem.retrieve(RetrievalRequest("new-task", TaskSplit.TRAIN, task.hard_constraints.category, task.raw_message, 3, 0))
    assert got == ()
    adapter = ScriptedModelAdapter(scripts)                                       # and a model generation sharing that store
    run(world, GenerationStore(MemoryBlobStore()), traces, adapter)
    for req in adapter.requests:
        for m in req.messages:
            if m.role == "assistant" and m.tool_name is None:
                assert not json.loads(m.content)["retrieved_episode_id"].startswith("g-scripted:")
