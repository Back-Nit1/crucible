"""Deterministic JSON + Markdown generation summary (no timestamps or host data, so reruns are byte-identical)."""
from __future__ import annotations

import json
from collections import Counter

from agents.actions import EpisodeRecord
from tasks.schemas import TaskSpec


def summarize(*, result, tasks: tuple[TaskSpec, ...], episodes: tuple[EpisodeRecord, ...], proposals, curated, next_pop,
              params: dict) -> dict:
    st, by_task = result.state, {t.id: t for t in tasks}
    kills = Counter(k["rule_id"] for e in episodes for k in e.kill_information)
    kills_by_agent = {a: dict(Counter(k["rule_id"] for e in episodes if e.agent_id == a for k in e.kill_information))
                      for a in st.checkpoint.killed_agent_ids}
    scored = [e for e in episodes if "fitness" in e.score_components]
    purchases = [e for e in episodes if e.termination in {"success"} or any(c.action.type == "confirm_and_pay" for c in e.tool_calls)]
    refusals_ok = [e for e in episodes if e.termination == "no_match" and not e.killed and by_task[e.task_id].is_impossible]
    return {
        "generation_id": result.generation_id, "status": st.status.value, "params": params,
        "compat": st.compat.model_dump(), "checkpoint_content_hash": st.checkpoint.content_hash(),
        "tasks": {"total": len(tasks), "feasible": sum(not t.is_impossible for t in tasks),
                  "impossible": sum(t.is_impossible for t in tasks), "review_traps": sum(t.is_review_trap for t in tasks),
                  "by_split": dict(Counter(t.split.value for t in tasks)),
                  "by_category": dict(Counter(t.hard_constraints.category for t in tasks))},
        "episodes": {"expected": len(st.checkpoint.genomes) * len(st.checkpoint.task_ids), "completed": len(st.checkpoint.completed_episode_keys),
                     "traced": len(episodes), "scored": len(scored), "by_termination": dict(Counter(e.termination for e in episodes)),
                     "script_unavailable": sum(o.termination == "script_unavailable" for o in st.outcomes.values())},
        "kills": {"episodes_killed": sum(e.killed for e in episodes), "by_rule": dict(kills), "killed_agents": list(st.checkpoint.killed_agent_ids),
                  "by_agent": kills_by_agent},
        "safety": {"completed_purchases": sum(e.termination == "success" and not e.killed for e in episodes),
                   "hallucinated_purchases": sum(any(k["rule_id"] == "K001_HALLUCINATED_PRODUCT" for k in e.kill_information)
                                                 and bool(e.payment_state.get("completed")) for e in episodes),
                   "budget_violations_charged": sum(any(k["rule_id"] == "K003_BUDGET_VIOLATION" for k in e.kill_information)
                                                    and bool(e.payment_state.get("completed")) for e in episodes),
                   "budget_attempts_blocked": sum(any(k["rule_id"] == "K003_BUDGET_VIOLATION" for k in e.kill_information) for e in episodes),
                   "correct_no_match_on_impossible": len(refusals_ok),
                   "impossible_tasks_run": sum(by_task[e.task_id].is_impossible for e in episodes)},
        "fitness": {"best": str(st.summary.best_fitness), "mean": str(st.summary.mean_fitness),
                    "by_genome": {g: str(v) for g, v in sorted(st.checkpoint.fitness.items())}},
        "survivors": list(st.summary.survivor_ids), "population": [
            {"id": g.id, "variant": g.system_prompt_variant, "parent": g.parent_id} for g in st.checkpoint.genomes],
        "loophole_hunter_proposals": [{"rule_id": c.rule_id, "state": c.state.value, "episodes": len(c.affected_episode_ids),
                                       "evidence": list(c.evidence)[:3]} for c in proposals],
        "training_curation": {"records": len(curated.records), "manifest_content_hash": curated.manifest.content_hash,
                              "exclusions": dict(Counter(curated.exclusions.values()))},
        "next_population": [g.id for g in next_pop],
        "inert_fixtures": sorted(result.inert_fixtures),
        "note": "Scripted shoppers read the task reference answer: this is pipeline evidence, not model performance.",
    }


def to_markdown(s: dict) -> str:
    k, sf, e, f = s["kills"], s["safety"], s["episodes"], s["fitness"]
    rows = ["# Generation " + s["generation_id"], "", f"Status: **{s['status']}** · scripted shoppers · mock payments only", "",
            "## Tasks", f"{s['tasks']['total']} total: {s['tasks']['feasible']} feasible, {s['tasks']['impossible']} impossible, "
            f"{s['tasks']['review_traps']} review-sensitive. Splits: {s['tasks']['by_split']}.", "",
            "## Episodes", f"{e['completed']}/{e['expected']} completed, {e['traced']} traced, {e['scored']} scored. "
            f"Terminations: {e['by_termination']}.", "",
            "## Kills", f"{k['episodes_killed']} episodes killed. By rule: {k['by_rule']}.", "",
            "## Safety", f"- completed purchases: {sf['completed_purchases']}",
            f"- hallucinated purchases: {sf['hallucinated_purchases']}", f"- budget violations charged: {sf['budget_violations_charged']} "
            f"(attempts blocked at the guard: {sf['budget_attempts_blocked']})",
            f"- correct no-match on impossible tasks: {sf['correct_no_match_on_impossible']} of {sf['impossible_tasks_run']}", "",
            "## Fitness", f"best {f['best']} · mean {f['mean']} · survivors {len(s['survivors'])}/{len(s['population'])}", "",
            "| Agent | Variant | Fitness | Killed |", "|---|---|---:|---|"]
    for g in s["population"]:
        rows.append(f"| {g['id']} | {g['variant']} | {f['by_genome'].get(g['id'], '-')} | {', '.join(k['by_agent'].get(g['id'], {})) or '-'} |")
    rows += ["", "## Loophole Hunter (proposals only, none enabled)"]
    rows += [f"- `{p['rule_id']}`: {p['episodes']} episode(s)" for p in s["loophole_hunter_proposals"]] or ["- none"]
    rows += ["", "## Training curation", f"{s['training_curation']['records']} grounded survivor records; exclusions {s['training_curation']['exclusions']}.",
             "", s["note"], ""]
    return "\n".join(rows)


def write(summary: dict, out_dir) -> None:
    from pathlib import Path
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    (out / "summary.md").write_text(to_markdown(summary))
