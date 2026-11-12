"""Observatory API: a generation picker, one cached bundle per generation (a focus episode plus a crowd of up to 30
replays), and a live server-sent-event stream (new episodes as they land in the trace store, and training progress
from training.live). Read-only; same whitelists as api.world.

Caching: a completed, published generation never changes, so its bundle is kept (LRU, 16 entries) until restart and
served with a long Cache-Control. Anything still running is cached for a few seconds only."""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from collections import OrderedDict, defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.world import (EpisodeDetail, EpisodeOut, GenerationDetail, KillRuleOut, LeaderboardRow, WorldReader, _detail,
                       _episode, gen_out, kill_rule_rows, leaderboard_rows)
from memory import TraceRecord

MAX_AGENTS = 60
STREAM_SECONDS = 15 * 60  # then the browser's EventSource reconnects on its own
POLL_SECONDS = 3.0
LIVE_TTL = 5.0


class CrowdStep(BaseModel):
    tool: str
    references: list[str]
    error_code: str | None


class CrowdEpisode(BaseModel):
    episode_id: str
    agent_id: str
    task_id: str
    category: str
    checkpoint: str | None
    killed: bool
    fitness: float | None
    termination: str
    products: list[str]  # products_considered: where this shopper can walk
    steps: list[CrowdStep]


class GenerationChoice(BaseModel):
    generation_id: str
    status: str  # published status, or "unpublished" (traces exist, no summary yet: running or interrupted)
    published: bool
    episodes: int
    population_size: int
    survivors: int


class Bundle(BaseModel):
    generation: GenerationDetail
    episodes: list[EpisodeOut]
    leaderboard: list[LeaderboardRow]
    kill_rules: list[KillRuleOut]
    focus: EpisodeDetail
    crowd: list[CrowdEpisode]


def crowd_episode(t: TraceRecord) -> CrowdEpisode:
    calls = t.episode.get("tool_calls", [])
    return CrowdEpisode(
        episode_id=t.episode_id, agent_id=t.agent_id, task_id=t.task_id, category=t.category,
        checkpoint=t.genome.get("model_checkpoint"), killed=t.killed, fitness=t.fitness if t.scored else None,
        termination=str(t.episode.get("termination", "unknown")), products=t.products_considered,
        steps=[CrowdStep(tool=c["action"]["type"], references=c.get("result_references", []), error_code=c.get("error_code"))
               for c in calls])


def pick_crowd(traces: list[TraceRecord], limit: int) -> list[TraceRecord]:
    """Round-robin across agents (longest episodes first per agent) so the crowd shows the whole population."""
    by: dict[str, list[TraceRecord]] = defaultdict(list)
    for t in sorted(traces, key=lambda t: (-len(t.episode.get("tool_calls", [])), t.episode_id)):
        by[t.agent_id].append(t)
    queues, out = [by[a] for a in sorted(by)], []
    while len(out) < limit and any(queues):
        for q in queues:
            if q and len(out) < limit:
                out.append(q.pop(0))
    return out


class Round(BaseModel):
    """One learning round of scripts.run_loop: its world run (generation `<iteration>-gen`), how the agents scored, and
    how far the round got (generate -> ... -> train -> evaluate -> reenter)."""
    iteration_id: str
    generation_id: str
    evidence: str | None  # model_rollouts | pipeline_evidence_scripted_dry_run
    policy: str | None  # who acted: scripted-v1 or model:qwen:<checkpoint>:<prompt>
    stages: dict[str, str]  # stage -> done | blocked | paused | failed | refused | killed
    next_stage: str | None
    produced_checkpoint: str | None  # the adapter this round trained (re-enters the next round)
    episodes: int
    mean_fitness: float | None
    kill_rate: float | None
    success_rate: float | None
    metrics_source: str  # summary (finished) | traces (live) | none


def _natural(name: str):
    return [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", name)]


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def _rate(n: int, d: int) -> float | None:
    return round(n / d, 4) if d else None


def rounds(root: Path, reader: WorldReader, trace_cache: dict) -> list[Round]:
    from scripts.run_loop import STAGES
    out = []
    for d in sorted((p for p in root.glob("*") if (p / "stages").is_dir()), key=lambda p: _natural(p.name)):
        files = {s: _read(d / "stages" / f"{s}.json") for s in STAGES if (d / "stages" / f"{s}.json").is_file()}
        gid = f"{d.name}-gen"
        summary = _read(d / "generation" / gid / "summary.json")
        metrics: dict = {"episodes": 0, "mean_fitness": None, "kill_rate": None, "success_rate": None, "metrics_source": "none"}
        policy = summary.get("policy") or None
        if summary:
            eps = summary.get("episodes", {})
            n = int(eps.get("completed", 0))
            mean = (summary.get("fitness") or {}).get("mean")
            metrics = {"episodes": n, "mean_fitness": float(mean) if mean is not None else None,
                       "kill_rate": _rate(int((summary.get("kills") or {}).get("episodes_killed", 0)), n),
                       "success_rate": _rate(int((eps.get("by_termination") or {}).get("success", 0)), n),
                       "metrics_source": "summary"}
        else:  # still running (or traces only): score it from the trace store, recomputed only when the count moves
            try:
                count = reader.traces({"generation_id": gid}, "episode_id", 0, 1)[1]
                if count and trace_cache.get(gid, (None,))[0] != count:
                    ts = reader.all_traces(gid)
                    trace_cache[gid] = (count, {
                        "episodes": len(ts), "mean_fitness": round(sum(t.fitness if t.scored else 0.0 for t in ts) / len(ts), 6),
                        "kill_rate": _rate(sum(t.killed for t in ts), len(ts)),
                        "success_rate": _rate(sum(t.episode.get("termination") == "success" for t in ts), len(ts)),
                        "metrics_source": "traces"}, ts[0].genome.get("model_checkpoint"))
                if count:
                    metrics, policy = trace_cache[gid][1], policy or trace_cache[gid][2]
            except Exception:  # noqa: BLE001 - trace store not configured: the round still shows its stages
                pass
        status = {s: str(b.get("status", "unknown")) for s, b in files.items()}
        out.append(Round(iteration_id=d.name, generation_id=gid, evidence=(files.get("generate") or {}).get("evidence"),
                         policy=policy, stages=status, next_stage=next((s for s in STAGES if status.get(s) != "done"), None),
                         produced_checkpoint=(files.get("reenter") or {}).get("checkpoint")
                         or (files.get("train") or {}).get("checkpoint_id"), **metrics))
    return out


def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def observatory_router(reader: WorldReader, training_source: Callable[[], list[dict]] = lambda: []) -> APIRouter:
    r = APIRouter(tags=["observatory"])
    cache: OrderedDict[tuple[str, int], tuple[float, Bundle]] = OrderedDict()
    trace_cache: dict = {}

    def current_rounds() -> list[dict]:
        root = Path(os.environ.get("CRUCIBLE_LOOP_ROOT", "checkpoints/loop"))
        return [x.model_dump() for x in rounds(root, reader, trace_cache)]

    def choices() -> list[GenerationChoice]:
        counts = reader.trace_generations()
        out = {d["gen_id"]: GenerationChoice(generation_id=d["gen_id"], status=d["status"], published=True,
                                             episodes=counts.get(d["gen_id"], 0), population_size=d.get("population_size", 0),
                                             survivors=d.get("survivors", 0)) for d in reader.generations()}
        for gid, n in counts.items():
            out.setdefault(gid, GenerationChoice(generation_id=gid, status="unpublished", published=False, episodes=n,
                                                 population_size=0, survivors=0))
        return sorted(out.values(), key=lambda g: g.generation_id, reverse=True)

    def build(gid: str, agents: int) -> tuple[Bundle, bool]:
        gens = reader.generations()
        doc = next((d for d in gens if d["gen_id"] == gid), None)
        traces = reader.all_traces(gid)
        if not traces:
            raise HTTPException(404, "generation_not_found")
        if doc is None:  # running or interrupted: no summary yet, describe it from its traces
            agents_seen = {t.agent_id for t in traces}
            generation = GenerationDetail(generation_id=gid, status="unpublished", population_size=len(agents_seen),
                                          survivors=0, kills=len({t.agent_id for t in traces if t.killed}), summary={})
        else:
            generation = GenerationDetail(**gen_out(doc).model_dump(), summary=doc.get("summary") or {})
        good = [t for t in traces if t.episode.get("termination") == "success" and not t.killed]
        focus = max(good or traces, key=lambda t: (len(t.episode.get("tool_calls", [])), t.episode_id))
        bundle = Bundle(generation=generation, episodes=[_episode(t) for t in traces[:200]],
                        leaderboard=leaderboard_rows(gens, traces), kill_rules=kill_rule_rows(traces),
                        focus=_detail(focus), crowd=[crowd_episode(t) for t in pick_crowd(traces, agents)])
        return bundle, doc is not None and doc["status"] == "completed"

    @r.get("/observatory/generations", response_model=list[GenerationChoice])
    def generations():
        return choices()

    @r.get("/observatory/rounds", response_model=list[Round])
    def learning_rounds():
        """Every scripts.run_loop round under CRUCIBLE_LOOP_ROOT (default checkpoints/loop), in order."""
        return current_rounds()

    @r.get("/observatory/training")
    def training():
        """Live training runs (training.live), newest first. Empty when CRUCIBLE_LIVE_TRAINING is not `modal`."""
        return {"runs": training_source()}

    @r.get("/observatory/{generation_id}", response_model=Bundle)
    def bundle(generation_id: str, response: Response, agents: Annotated[int, Query(ge=1, le=MAX_AGENTS)] = 30):
        key, now = (generation_id, agents), time.monotonic()
        hit = cache.get(key)
        if hit and hit[0] > now:
            cache.move_to_end(key)
            out, final = hit[1], hit[0] == float("inf")
        else:
            out, final = build(generation_id, agents)
            cache[key] = (float("inf") if final else now + LIVE_TTL, out)
            while len(cache) > 16:
                cache.popitem(last=False)
        response.headers["Cache-Control"] = "public, max-age=3600" if final else "no-cache"
        return out

    @r.get("/observatory/{generation_id}/live")
    async def live(generation_id: str, request: Request):
        """text/event-stream. Events: `status` {episodes}, `episode` CrowdEpisode (new since connect),
        `training` {runs}, `rounds` {rounds}. Sent only when something changed; a comment line every 15 s keeps proxies open."""
        async def events():
            def count() -> int:
                return reader.traces({"generation_id": generation_id}, "episode_id", 0, 1)[1]
            seen = {t.episode_id for t in await asyncio.to_thread(reader.all_traces, generation_id)}
            total, runs, loop, started, beat = len(seen), None, None, time.monotonic(), time.monotonic()
            yield "retry: 5000\n\n" + _sse("status", {"episodes": total})
            while time.monotonic() - started < STREAM_SECONDS and not await request.is_disconnected():
                latest_rounds = await asyncio.to_thread(current_rounds)
                if latest_rounds != loop:
                    loop = latest_rounds
                    yield _sse("rounds", {"rounds": loop})
                latest = await asyncio.to_thread(training_source)
                if latest != runs:
                    runs = latest
                    yield _sse("training", {"runs": runs})
                n = await asyncio.to_thread(count)
                if n != total:
                    total = n
                    fresh = [t for t in await asyncio.to_thread(reader.all_traces, generation_id) if t.episode_id not in seen]
                    for t in fresh[-30:]:
                        yield _sse("episode", crowd_episode(t).model_dump())
                    seen.update(t.episode_id for t in fresh)
                    yield _sse("status", {"episodes": total})
                if time.monotonic() - beat > 15:
                    beat = time.monotonic()
                    yield ": keep-alive\n\n"
                await asyncio.sleep(POLL_SECONDS)
        return StreamingResponse(events(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    return r
