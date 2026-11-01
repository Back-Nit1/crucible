"""Resumable, atomic, bounded-concurrency evaluation runner.

Every contender runs the identical (task, seed) matrix of one manifest through the REAL action state machine, guards
and scorer (world.runtime.run_one, MockPayments). One JSON artifact per (contender, task, seed) is written atomically,
so a re-run executes only what is missing and can never duplicate an episode. Finalization requires expected == unique."""
from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
import time
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from agents.actions import EpisodeRecord
from agents.model import AdapterPolicy, ModelAdapter
from agents.prompts import system_prompt
from catalog.providers.base import FrozenCatalogProvider
from eval.contenders import ContenderConfig
from eval.manifest import EvaluationManifest, RunStatus, assert_same_manifest
from eval.memory import FrozenEvalMemory
from tasks.schemas import TaskSpec
from world.evolution import Genome, MemorySettings, ReviewStrategy, SearchParameters
from world.runtime import episode_seed, run_one

ARTIFACT_VERSION = "1.0"
ModelFactory = Callable[[ContenderConfig], ModelAdapter]
Key = tuple[str, str, int]  # contender id, task id, seed


class EpisodeArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    artifact_version: str = ARTIFACT_VERSION
    manifest_hash: str
    contender_id: str
    contender_identity_hash: str
    task_id: str
    seed: int
    model_seed: int
    episode: EpisodeRecord
    wall_seconds: float
    written_at: dt.datetime


class Incomplete(RuntimeError):
    """Finalization was refused: expected records do not equal the unique records on disk."""


class EvaluationStore:
    """<root>/<evaluation_id>/{manifest.json, episodes/<contender>/<task>__<seed>.json, quarantine/...}"""

    def __init__(self, root: str | Path, evaluation_id: str):
        self.dir = Path(root) / evaluation_id

    def _write(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
        try:
            with os.fdopen(fd, "w") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)  # atomic: a reader sees the old file or the whole new one
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def episode_path(self, key: Key, quarantine: bool = False) -> Path:
        cid, tid, seed = key
        return self.dir / ("quarantine" if quarantine else "episodes") / cid / f"{tid}__{seed}.json"

    def save_manifest(self, manifest: EvaluationManifest) -> None:
        self._write(self.dir / "manifest.json", manifest.model_dump_json(indent=2) + "\n")

    def load_manifest(self) -> EvaluationManifest | None:
        path = self.dir / "manifest.json"
        return EvaluationManifest.model_validate_json(path.read_text()) if path.is_file() else None

    def save_episode(self, artifact: EpisodeArtifact, quarantine: bool = False) -> None:
        key = (artifact.contender_id, artifact.task_id, artifact.seed)
        self._write(self.episode_path(key, quarantine), artifact.model_dump_json(indent=1) + "\n")

    def load_episodes(self, manifest: EvaluationManifest, quarantine: bool = False) -> dict[Key, EpisodeArtifact]:
        """Every stored artifact, validated against the manifest. Foreign or unexpected artifacts are an error."""
        expected = {(c.id, t, s): c for c in manifest.contenders for t, s in manifest.pairs}
        out: dict[Key, EpisodeArtifact] = {}
        for path in sorted((self.dir / ("quarantine" if quarantine else "episodes")).glob("*/*.json")):
            artifact = EpisodeArtifact.model_validate_json(path.read_text())
            assert_same_manifest(manifest.manifest_hash, artifact.manifest_hash)
            key = (artifact.contender_id, artifact.task_id, artifact.seed)
            if key not in expected or path != self.episode_path(key, quarantine):
                raise ValueError(f"{path}: artifact is outside the manifest matrix")
            if artifact.contender_identity_hash != expected[key].identity_hash:
                raise ValueError(f"{path}: contender identity changed since the artifact was written")
            out[key] = artifact
        return out


@dataclass
class RunOutcome:
    executed: int = 0
    skipped_done: int = 0
    quarantined: int = 0
    status: RunStatus = RunStatus.RUNNING
    stopped_reason: str | None = None
    unique_records: int = 0
    memory_pool_size: int = 0

    @property
    def complete(self) -> bool:
        return self.stopped_reason is None and self.status is RunStatus.RUNNING


def contender_genome(c: ContenderConfig) -> Genome:
    return Genome(id=c.id, system_prompt_variant=c.system_prompt_variant, search=SearchParameters(), reviews=ReviewStrategy(),
                  memory=MemorySettings(enabled=c.memory_enabled, k=c.memory_k), temperature=c.temperature,
                  model_checkpoint=c.request_checkpoint)


def is_backend_failure(episode: EpisodeRecord) -> bool:
    """Model call failed at the transport/backend boundary (not a malformed-but-delivered answer)."""
    return (episode.termination == "model_failure" and episode.final_answer.startswith("model failure:")
            and "MalformedModelOutput" not in episode.final_answer)


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def run_evaluation(manifest: EvaluationManifest, tasks: dict[str, TaskSpec], *, catalog: FrozenCatalogProvider,
                   model_factory: ModelFactory, store: EvaluationStore, memory: FrozenEvalMemory | None = None,
                   max_workers: int = 1, max_episodes: int | None = None, max_consecutive_backend_failures: int = 3,
                   log: Callable[[str], None] = lambda m: None, clock: Callable[[], dt.datetime] = _now) -> RunOutcome:
    """Run (or resume) the manifest. Re-running executes only the missing (contender, task, seed) records."""
    if manifest.payment_backend != "mock":
        raise ValueError("evaluation runs use MockPayments only; sandbox payments are not supported here")
    ordered = manifest.verify_tasks(tasks)
    if any(c.memory_enabled for c in manifest.contenders):
        if memory is None or memory.pool_size == 0:
            raise ValueError("a memory contender needs a non-empty audited memory pool; base+memory would equal base")
        if manifest.memory_pool_size != memory.pool_size:
            raise ValueError("memory pool differs from the manifest")
    existing = store.load_manifest()
    if existing is not None:
        assert_same_manifest(existing.manifest_hash, manifest.manifest_hash)
    done = store.load_episodes(manifest)
    by_task = {t.id: t for t in ordered}
    by_contender = {c.id: c for c in manifest.contenders}
    pending = [(c.id, t, s) for t, s in manifest.pairs for c in manifest.contenders if (c.id, t, s) not in done]
    out = RunOutcome(skipped_done=len(done), unique_records=len(done), memory_pool_size=memory.pool_size if memory else 0)
    if max_episodes is not None:
        pending = pending[:max_episodes]
    attempts = (existing.resume.attempts if existing else 0) + 1
    state = {"manifest": manifest.with_state(status=RunStatus.RUNNING,
                                             resume=manifest.resume.model_copy(update={"attempts": attempts}))}

    def checkpoint(status: RunStatus, error: str | None = None) -> None:
        resume = state["manifest"].resume.model_copy(update={
            "completed_records": out.unique_records, "last_checkpoint_at": clock(), "error": error})
        state["manifest"] = state["manifest"].with_state(status=status, resume=resume)
        store.save_manifest(state["manifest"])

    def execute(key: Key) -> EpisodeArtifact:
        cid, tid, seed = key
        contender, task = by_contender[cid], by_task[tid]
        genome, mseed = contender_genome(contender), episode_seed(seed, tid)  # same request seed for every contender
        adapter = model_factory(contender)

        def policy_factory(task_, genome_, agent_id, _ignored_seed):
            return AdapterPolicy(adapter, system_prompt(contender.system_prompt_variant), seed=mseed, temperature=contender.temperature,
                                 request_id=f"{manifest.evaluation_id}:{cid}:{tid}:s{seed}", checkpoint=contender.request_checkpoint)
        started = time.monotonic()
        episode = run_one(task, genome, catalog=catalog, generation_id=manifest.evaluation_id, seed=seed,
                          memory=memory if contender.memory_enabled else None, policy_factory=policy_factory)
        episode = episode.model_copy(update={"episode_id": f"{manifest.evaluation_id}:{cid}:{tid}:s{seed}"})
        return EpisodeArtifact(manifest_hash=manifest.manifest_hash, contender_id=cid, contender_identity_hash=contender.identity_hash,
                               task_id=tid, seed=seed, model_seed=mseed, episode=episode,
                               wall_seconds=round(time.monotonic() - started, 6), written_at=clock())

    checkpoint(RunStatus.RUNNING)
    streak: list[EpisodeArtifact] = []
    stop = False
    try:
        with ThreadPoolExecutor(max_workers=max(1, max_workers)) as pool:
            queue, running = list(pending), {}
            while (queue or running) and not stop:
                while queue and len(running) < max(1, max_workers):
                    key = queue.pop(0)
                    running[pool.submit(execute, key)] = key
                finished, _ = wait(running, return_when=FIRST_COMPLETED)
                for future in finished:
                    running.pop(future)
                    artifact = future.result()  # a non-model exception is a bug: fail the run loudly
                    if is_backend_failure(artifact.episode):
                        streak.append(artifact)
                        if len(streak) >= max_consecutive_backend_failures:
                            stop = True
                            break
                        store.save_episode(artifact)  # isolated failures are real, counted results
                    else:
                        streak.clear()
                        store.save_episode(artifact)
                    out.executed += 1
                    out.unique_records += 1
                    log(f"{out.unique_records}/{manifest.expected_records} {artifact.contender_id} {artifact.task_id} "
                        f"s{artifact.seed} {artifact.episode.termination}")
                    checkpoint(RunStatus.RUNNING)
            if stop:
                for f in running:
                    f.cancel()
    except BaseException as exc:
        checkpoint(RunStatus.FAILED if isinstance(exc, Exception) else RunStatus.INTERRUPTED, type(exc).__name__)
        raise
    if stop:
        # the outage episodes that tripped the breaker are quarantined (kept, visible) and re-run on resume: a dead
        # backend must not become permanent "model failures" in the results. Earlier isolated failures stay as results.
        for artifact in streak:
            store.save_episode(artifact, quarantine=True)
            store.episode_path((artifact.contender_id, artifact.task_id, artifact.seed)).unlink(missing_ok=True)
        # earlier members of the streak were saved as results before the trip: demoted by the unlink above
        out.quarantined = len(streak)
        out.unique_records = len(store.load_episodes(manifest))
        out.executed = out.unique_records - out.skipped_done
        out.status, out.stopped_reason = RunStatus.INTERRUPTED, f"{len(streak)} consecutive backend failures"
    else:
        out.unique_records = len(store.load_episodes(manifest))
        # all records present: stays "running" until finalize() verifies and marks the manifest completed
        out.status = RunStatus.INTERRUPTED if out.unique_records < manifest.expected_records else RunStatus.RUNNING
    checkpoint(out.status, out.stopped_reason)
    return out


def finalize(manifest: EvaluationManifest, store: EvaluationStore) -> dict[str, tuple[EpisodeRecord, ...]]:
    """contender id -> its episodes, only if expected == unique records and every pair is covered by every contender."""
    done = store.load_episodes(manifest)
    if len(done) != manifest.expected_records:
        raise Incomplete(f"cannot finalize: expected {manifest.expected_records} records, found {len(done)} unique")
    runs = {}
    for c in manifest.contenders:
        eps = tuple(done[(c.id, t, s)].episode for t, s in manifest.pairs)
        runs[c.id] = eps
    store.save_manifest(manifest.with_state(
        status=RunStatus.COMPLETED, resume=manifest.resume.model_copy(update={"completed_records": len(done)})))
    return runs
