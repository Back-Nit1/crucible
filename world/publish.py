"""Publish generation + kill-rule summaries to Elastic so the (separately hosted) API/dashboards can read them.
Idempotent: documents are keyed by generation id / rule id+version."""
from __future__ import annotations

import datetime as dt

from scoring.kill_rules import INITIAL_RULES

GENERATIONS_EXTRA = {"summary": {"type": "object", "enabled": False}, "error": {"type": "keyword"}, "runner": {"type": "keyword"},
                     "published_at": {"type": "date"}}


def generation_doc(state, summary: dict | None, runner: str = "local", published_at: str | None = None) -> dict:
    cp, s = state.checkpoint, state.summary
    return {
        "gen_id": cp.generation_id, "generation": 0, "status": state.status.value, "population_size": len(cp.genomes),
        "survivors": len(s.survivor_ids) if s else 0, "kills": len(cp.killed_agent_ids),
        "started_at": None, "finished_at": None,  # wall-clock times are deliberately not part of the deterministic record
        "config": {"seed": cp.seed, "tasks": len(cp.task_ids), "catalog_hash": state.compat.catalog_hash,
                   "rules_version": state.compat.rules_version, "checkpoint_hash": cp.content_hash()},
        "summary": summary or {}, "error": state.error, "runner": runner,
        # When this doc was written: orders the archive newest-first. Lives on the published doc, never the checkpoint.
        "published_at": published_at}


def publish_generation(es, state, summary: dict | None, runner: str = "local", published_at: str | None = None) -> None:
    """Also called for unfinished runs (summary=None), so a running or interrupted generation is visible too.
    `published_at` defaults to now; backfills pass the run's own time so republishing never reorders the archive."""
    es.call("PUT", f"/{es.ix('generations')}/_mapping", {"properties": GENERATIONS_EXTRA})
    at = published_at or dt.datetime.now(dt.timezone.utc).isoformat()
    es.bulk("generations", [(state.checkpoint.generation_id, generation_doc(state, summary, runner, at))])


def task_items(tasks) -> list[dict]:
    """Real per-task facts the Observatory shows per world (the budget is the task's, never the policy's reading of it)."""
    return [{"id": t.id, "category": t.hard_constraints.category, "max_total": str(t.hard_constraints.max_total),
             "impossible": t.is_impossible, "review_trap": t.is_review_trap} for t in tasks]


def with_task_items(summary: dict | None, tasks, task_ids) -> dict | None:
    """Backfill `tasks.items` from a regenerated task set, only when it is provably the same set (same ids, same order)."""
    if summary is None or "items" in summary.get("tasks", {}) or [t.id for t in tasks] != list(task_ids):
        return summary
    return {**summary, "tasks": {**summary.get("tasks", {}), "items": task_items(tasks)}}


def kill_rule_docs(counts: dict[str, int]) -> list[tuple[str, dict]]:
    return [(f"{r.id}:v{r.version}", {"rule_id": r.id, "version": r.version, "description": r.description,
                                      "added_at": r.added_on.isoformat(), "enabled": r.enabled, "kills": counts.get(r.id, 0)})
            for r in INITIAL_RULES]


def publish_kill_rules(es, counts: dict[str, int]) -> None:
    es.call("PUT", f"/{es.ix('kill_rules')}/_mapping", {"properties": {"enabled": {"type": "boolean"}}})
    es.bulk("kill_rules", kill_rule_docs(counts))
