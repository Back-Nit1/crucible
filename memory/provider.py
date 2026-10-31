"""Repository-backed implementation of `agents.memory.MemoryProvider`.

Persists EVERY episode (the traces index is the full record); retrieval enforces the safety rules:
  * split not in {test, held_out_category} (stricter than `split != test`: held-out categories must stay unseen),
  * killed = false, fitness >= request.minimum_fitness,
  * a request from the test split retrieves nothing, k <= 0 retrieves nothing,
  * deterministic order: same category first, then similarity (rounded to 4 dp) desc, fitness desc, episode_id asc.
The rules are applied in the repository query AND re-checked here, so a misbehaving repository cannot leak a trace."""
from agents.actions import EpisodeRecord
from agents.memory import RetrievalRequest
from memory import PROTECTED_SPLITS, TraceRecord, TraceRepository
from memory.adapter import trace_from_episode
from tasks.schemas import TaskSplit

POOL_FACTOR = 5  # candidates fetched per requested item, so category/fitness re-ranking has room to work


class TraceMemoryProvider:
    def __init__(self, repo: TraceRepository, *, catalog_snapshot_id: str = "", catalog_manifest_hash: str = "",
                 provenance: dict | None = None):
        self.repo, self.snapshot_id, self.manifest_hash = repo, catalog_snapshot_id, catalog_manifest_hash
        self.provenance = provenance or {}

    def store(self, episode: EpisodeRecord, *, split: TaskSplit, category: str, fitness: float) -> None:
        self.repo.add(trace_from_episode(episode, split=split, category=category, fitness=fitness,
                                         catalog_snapshot_id=self.snapshot_id, catalog_manifest_hash=self.manifest_hash,
                                         provenance=self.provenance))

    def retrieve(self, request: RetrievalRequest) -> tuple[EpisodeRecord, ...]:
        if request.k <= 0 or request.split in (TaskSplit.TEST, TaskSplit.HELD_OUT_CATEGORY):
            return ()
        hits = self.repo.search(request.query, max(request.k * POOL_FACTOR, 25), request.minimum_fitness)
        safe = [(t, s) for t, s in hits if self._allowed(t, request)]
        safe.sort(key=lambda h: (h[0].category != request.category, -round(h[1], 4), -h[0].fitness, h[0].episode_id))
        return tuple(EpisodeRecord.model_validate(t.episode) for t, _ in safe[:request.k])

    @staticmethod
    def _allowed(t: TraceRecord, request: RetrievalRequest) -> bool:
        return (t.split not in PROTECTED_SPLITS and not t.killed and t.fitness >= request.minimum_fitness
                and t.task_id != request.task_id)  # never hand an episode its own past answer
