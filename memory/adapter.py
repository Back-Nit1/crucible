"""EpisodeRecord (agents.actions) -> TraceRecord. One code path for both the `task`-aware and `MemoryProvider.store` callers."""
from decimal import Decimal

from agents.actions import EpisodeRecord, ParseIntent
from memory import TraceRecord
from tasks.schemas import TaskSpec, TaskSplit


def episode_fitness(episode: EpisodeRecord) -> float:
    """Fitness from the scorer's own components; an unscored episode (malformed/limit/failed) has fitness 0."""
    raw = episode.score_components.get("fitness")
    return float(Decimal(str(raw))) if raw is not None else 0.0


def raw_message(episode: EpisodeRecord) -> str:
    """The shopper message the episode answered: the (mandatory) first parse_intent call carries it verbatim."""
    first = episode.tool_calls[0].action if episode.tool_calls else None
    return first.raw_message if isinstance(first, ParseIntent) else ""


def trace_from_episode(episode: EpisodeRecord, *, split: TaskSplit | str, category: str, fitness: float | None = None,
                       task_text: str | None = None, catalog_snapshot_id: str = "", catalog_manifest_hash: str = "",
                       provenance: dict | None = None) -> TraceRecord:
    rules = [str(k["rule_id"]) for k in episode.kill_information if "rule_id" in k]
    return TraceRecord(
        episode_id=episode.episode_id, task_id=episode.task_id, agent_id=episode.agent_id,
        generation_id=episode.generation_id, split=split.value if isinstance(split, TaskSplit) else split,
        category=category, task_text=task_text if task_text is not None else raw_message(episode),
        killed=episode.killed, kill_reason=rules[0] if rules else None, kill_rule_ids=rules,
        fitness=episode_fitness(episode) if fitness is None else fitness, termination=str(episode.termination),
        seed=episode.seed, catalog_snapshot_id=catalog_snapshot_id, catalog_manifest_hash=catalog_manifest_hash,
        calls=[c.action.type for c in episode.tool_calls],
        provenance={"episode_schema_version": episode.schema_version, "started_at": episode.started_at.isoformat(),
                    "ended_at": episode.ended_at.isoformat(), "token_count": episode.token_count,
                    "cost": str(episode.cost), **(provenance or {})},
        episode=episode.model_dump(mode="json"))


def to_trace_record(episode: EpisodeRecord, task: TaskSpec, *, provenance: dict | None = None) -> TraceRecord:
    """Full mapping when the TaskSpec is at hand (split, category, message, seed and catalog hash come from the task)."""
    return trace_from_episode(
        episode, split=task.split, category=task.hard_constraints.category, task_text=task.raw_message,
        catalog_snapshot_id=task.catalog_snapshot_id, catalog_manifest_hash=task.catalog_manifest_hash,
        provenance={"task_seed": task.seed, "task_difficulty": task.difficulty.value,
                    "is_impossible": task.is_impossible, "is_review_trap": task.is_review_trap, **(provenance or {})})
