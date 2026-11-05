"""Publish generation + kill-rule summaries to Elastic so the (separately hosted) API/dashboards can read them.
Idempotent: documents are keyed by generation id / rule id+version."""
from __future__ import annotations


from scoring.kill_rules import INITIAL_RULES

GENERATIONS_EXTRA = {"summary": {"type": "object", "enabled": False}, "error": {"type": "keyword"}, "runner": {"type": "keyword"}}


def generation_doc(state, summary: dict | None, runner: str = "local") -> dict:
    cp, s = state.checkpoint, state.summary
    return {
        "gen_id": cp.generation_id, "generation": 0, "status": state.status.value, "population_size": len(cp.genomes),
        "survivors": len(s.survivor_ids) if s else 0, "kills": len(cp.killed_agent_ids),
        "started_at": None, "finished_at": None,  # wall-clock times are deliberately not part of the deterministic record
        "config": {"seed": cp.seed, "tasks": len(cp.task_ids), "catalog_hash": state.compat.catalog_hash,
                   "rules_version": state.compat.rules_version, "checkpoint_hash": cp.content_hash()},
        "summary": summary or {}, "error": state.error, "runner": runner}


def publish_generation(es, state, summary: dict | None, runner: str = "local") -> None:
    es.call("PUT", f"/{es.ix('generations')}/_mapping", {"properties": GENERATIONS_EXTRA})
    es.bulk("generations", [(state.checkpoint.generation_id, generation_doc(state, summary, runner))])


def kill_rule_docs(counts: dict[str, int]) -> list[tuple[str, dict]]:
    return [(f"{r.id}:v{r.version}", {"rule_id": r.id, "version": r.version, "description": r.description,
                                      "added_at": r.added_on.isoformat(), "enabled": r.enabled, "kills": counts.get(r.id, 0)})
            for r in INITIAL_RULES]


def publish_kill_rules(es, counts: dict[str, int]) -> None:
    es.call("PUT", f"/{es.ix('kill_rules')}/_mapping", {"properties": {"enabled": {"type": "boolean"}}})
    es.bulk("kill_rules", kill_rule_docs(counts))
