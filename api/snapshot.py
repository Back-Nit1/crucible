"""One compact, capped snapshot of a generation for the Observatory: every episode as a short path of stops.

Indices replace repeated strings so 2,400 episodes stay small. Stop kinds:
0 spawn · 1 exchange · 2 shop (ref = category index) · 3 product (ref = product index) · 4 checkout · 5 refusal.
"""
from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Sequence

from memory import TraceRecord
from memory.episodes import privileged

SPAWN, EXCHANGE, SHOP, PRODUCT, CHECKOUT, REFUSAL = range(6)


def _hash(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def path_for(calls: list[dict], product_index: dict[str, int], category_index: int) -> list[list[int]]:
    path = [[SPAWN, -1]]
    for c in calls:
        tool = c.get("action", {}).get("type", "")
        if tool == "parse_intent":
            stop = [SPAWN, -1]
        elif tool == "search_catalog":
            stop = [EXCHANGE, -1]
        elif tool == "report_no_match":
            stop = [REFUSAL, -1]
        elif "purchase" in tool or "pay" in tool:
            stop = [CHECKOUT, -1]
        else:
            # The product a step acts on (reviews reference review ids, so arguments come first), else what it returned.
            ids = [c.get("arguments", {}).get("product_id"), *c.get("result_references", [])]
            ref = next((product_index[r] for r in ids if r in product_index), None)
            stop = [PRODUCT, ref] if ref is not None else [SHOP, category_index]
        if stop != path[-1]:
            path.append(stop)
    return path


def _scripted(summary: dict, traces: Sequence[TraceRecord]) -> bool | None:
    """True/False from the summary, else from the traces' checkpoints (running runs publish `summary: {}`).
    None when nothing is recorded yet: the UI must never default an unknown run to "Qwen"."""
    if (summary.get("params") or {}).get("model") == "scripted" or summary.get("policy") == "scripted-v1":
        return True
    if summary.get("policy") or (summary.get("params") or {}).get("model"):
        return False
    return any(privileged(t) for t in traces) if traces else None


def build_snapshot(gen: dict, traces: Sequence[TraceRecord], categories: Sequence[str], *,
                   max_episodes: int = 5000, max_products: int = 3000) -> dict:
    summary = gen.get("summary") or {}
    total = len(traces)
    kept = sorted(traces, key=lambda t: _hash(t.episode_id))[:max_episodes] if total > max_episodes else traces
    kept = sorted(kept, key=lambda t: t.episode_id)

    cats = list(categories) + sorted({t.category for t in kept} - set(categories))
    cat_ix = {c: i for i, c in enumerate(cats)}

    mentions = Counter(p for t in kept for p in t.products_considered)
    product_cat = {p: t.category for t in kept for p in t.products_considered}
    top = sorted(mentions, key=lambda p: (-mentions[p], p))[:max_products]
    prod_ix = {p: i for i, p in enumerate(top)}

    items = {i["id"]: i for i in (summary.get("tasks") or {}).get("items", [])}
    task_ids = sorted({t.task_id for t in kept})
    first = {}
    for t in kept:
        first.setdefault(t.task_id, t)
    worlds = [{"task_id": tid, "category": first[tid].category, "request": first[tid].task_text,
               "budget": items.get(tid, {}).get("max_total"), "impossible": items.get(tid, {}).get("impossible"),
               "review_trap": items.get(tid, {}).get("review_trap")} for tid in task_ids]
    world_ix = {tid: i for i, tid in enumerate(task_ids)}

    pop = summary.get("population") or []
    agent_ids = [p["id"] for p in pop]
    agent_ids += sorted({t.agent_id for t in kept} - set(agent_ids))  # every episode's agent must be indexable
    variants = {p["id"]: p.get("variant") for p in pop}
    fitness = (summary.get("fitness") or {}).get("by_genome", {})
    survivors = set(summary.get("survivors") or [])
    kills_by = (summary.get("kills") or {}).get("by_agent", {})
    agents = [{"id": a, "variant": variants.get(a), "fitness": float(fitness[a]) if a in fitness else None,
               "survivor": a in survivors, "kill_rules": sorted(kills_by.get(a, {}))} for a in agent_ids]
    agent_ix = {a: i for i, a in enumerate(agent_ids)}

    episodes = [{"id": t.episode_id, "agent": agent_ix[t.agent_id], "world": world_ix[t.task_id],
                 "path": path_for(t.episode.get("tool_calls", []), prod_ix, cat_ix[t.category]),
                 "termination": str(t.episode.get("termination", "unknown")), "killed": t.killed,
                 "fitness": t.fitness if t.scored else None} for t in kept]

    return {
        "generation_id": gen["gen_id"], "published_at": gen.get("published_at"),
        "scripted": _scripted(summary, kept),
        "policy": summary.get("policy"), "population_size": gen.get("population_size", 0),
        "survivors": gen.get("survivors", 0), "kills": gen.get("kills", 0),
        "categories": [{"id": c, "name": c.replace("_", " "),
                        "product_count": sum(product_cat[p] == c for p in top)} for c in cats],
        "worlds": worlds, "agents": agents,
        "products": [{"id": p, "category": product_cat[p], "mentions": mentions[p]} for p in top],
        "episodes": episodes,
        "limits": {"episodes_total": total, "episodes_included": len(kept),
                   # expected = every (agent, task) pair; untraced = episodes the scripted shopper skipped (no trace)
                   "episodes_expected": (summary.get("episodes") or {}).get("expected"),
                   "episodes_untraced": (summary.get("episodes") or {}).get("script_unavailable"),
                   "products_total": len(mentions),
                   "products_included": len(top), "sampled": total > max_episodes},
    }
