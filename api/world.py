"""World, model and ledger read API for the dashboards + the agent-run contract for the chat (Phase 9).

Reads go through a `WorldReader` (Elastic in production, in-memory for tests/sample data). Responses are typed,
paginated (`offset`/`limit`), filterable and sortable by a fixed whitelist. Nothing here returns credentials, tokens,
approval URLs, browser data, shopper PII or exception bodies."""
from __future__ import annotations

import datetime as dt
from collections import Counter, defaultdict
from decimal import Decimal
from typing import Annotated, Generic, Literal, Protocol, TypeVar

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from memory import TraceRecord
from scoring.kill_rules import INITIAL_RULES

T = TypeVar("T")
MAX_LIMIT = 200
Limit = Annotated[int, Query(ge=1, le=MAX_LIMIT)]
Offset = Annotated[int, Query(ge=0, le=100_000)]


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    offset: int
    limit: int


# --- response schemas (stable: the frontend codes against these) -------------------------------------------------
class GenerationOut(BaseModel):
    generation_id: str
    status: str
    population_size: int
    survivors: int
    kills: int
    seed: int | None = None
    tasks: int | None = None
    catalog_hash: str | None = None
    runner: str | None = None
    error: str | None = None
    published_at: str | None = None


class GenerationDetail(GenerationOut):
    summary: dict = Field(default_factory=dict)  # deterministic run summary (episodes, kills by rule, safety, loophole proposals)


class EpisodeOut(BaseModel):
    episode_id: str
    task_id: str
    agent_id: str
    generation_id: str
    split: str
    category: str
    fitness: float | None  # None when the episode was never scored
    scored: bool
    killed: bool
    kill_rule_id: str | None
    kill_rule_version: int | None
    termination: str
    tool_call_count: int
    products_considered: list[str]
    review_ids_cited: list[str]
    final_answer: str


class ReplayStep(BaseModel):
    sequence: int
    tool: str
    arguments: dict
    result_references: list[str]
    result_summary: str
    error_code: str | None
    timestamp: dt.datetime


class KillOut(BaseModel):
    rule_id: str
    rule_version: int
    description: str
    evidence: list[str]


class EpisodeDetail(EpisodeOut):
    task_text: str
    catalog_hash: str | None
    seed: int | None
    replay: list[ReplayStep]
    score_components: dict
    kills: list[KillOut]
    payment_events: list[dict]
    genome: dict


class LeaderboardRow(BaseModel):
    rank: int
    agent_id: str
    variant: str
    generation_id: str
    episodes: int
    mean_fitness: float
    killed_episodes: int
    kill_rules: list[str]
    survivor: bool


class KillLogRow(BaseModel):
    episode_id: str
    agent_id: str
    generation_id: str
    task_id: str
    rule_id: str
    rule_version: int
    evidence: list[str]


class KillRuleOut(BaseModel):
    rule_id: str
    version: int
    description: str
    added_on: dt.date
    enabled: bool
    kills: int


class LedgerRow(BaseModel):
    mode: Literal["mock", "sandbox"]
    episode_id: str
    event: str
    product_id: str | None = None
    amount: str | None = None
    references: list[str]  # order / capture ids (mock ids in world runs)


class DocumentOut(BaseModel):
    id: str
    data: dict


class AgentRunRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    mode: Literal["trained", "base", "scripted"] = "trained"


class ReviewEvidenceOut(BaseModel):
    claim: str
    review_ids: list[str]
    excerpt: str | None = None
    rating: float | None = None
    date: dt.date | None = None


class PickOut(BaseModel):
    product_id: str
    title: str
    price: Decimal
    currency: str
    source: str
    as_of: dt.datetime
    snapshot: bool
    reason: str
    review_evidence: list[ReviewEvidenceOut]


class AgentRunResult(BaseModel):
    parsed_intent: dict
    steps: list[ReplayStep]
    picks: list[PickOut]
    no_match: bool = False
    closest_product_id: str | None = None
    assumptions: list[str]
    final_answer: str
    model: str
    latency_ms: int | None = None
    cost_usd: Decimal | None = None
    run_id: str | None = None  # set when produced by the buyer service: confirm via POST /agent/runs/{run_id}/confirm
    status: str | None = None  # running | awaiting_confirmation | completed | failed


class ModelUnavailable(Exception):
    """No model endpoint/checkpoint is configured for this deployment."""


class WorldDataUnavailable(Exception):
    """The trace/generation store is not configured for this deployment."""


class AgentRunner(Protocol):
    def run(self, request: AgentRunRequest) -> AgentRunResult: ...


class UnconfiguredRunner:
    def run(self, request: AgentRunRequest) -> AgentRunResult:
        raise ModelUnavailable("no model endpoint is configured")


class WorldReader(Protocol):
    def generations(self) -> list[dict]: ...
    def traces(self, filters: dict, sort: str, offset: int, limit: int) -> tuple[list[TraceRecord], int]: ...
    def trace(self, episode_id: str) -> TraceRecord | None: ...
    def all_traces(self, generation_id: str | None = None) -> list[TraceRecord]: ...
    def documents(self, kind: str, offset: int, limit: int) -> tuple[list[dict], int]: ...


EPISODE_SORTS = {"fitness", "episode_id", "agent_id", "generation_id", "category", "killed"}


def _episode(t: TraceRecord) -> EpisodeOut:
    ep = t.episode
    return EpisodeOut(
        episode_id=t.episode_id, task_id=t.task_id, agent_id=t.agent_id, generation_id=t.generation_id, split=t.split,
        category=t.category, fitness=t.fitness if t.scored else None, scored=t.scored, killed=t.killed,
        kill_rule_id=t.kill_reason, kill_rule_version=t.kill_rule_version, termination=str(ep.get("termination", "unknown")),
        tool_call_count=len(ep.get("tool_calls", [])), products_considered=t.products_considered,
        review_ids_cited=t.review_ids_cited, final_answer=t.final_answer)


def _detail(t: TraceRecord) -> EpisodeDetail:
    calls = t.episode.get("tool_calls", [])
    return EpisodeDetail(
        **_episode(t).model_dump(), task_text=t.task_text, catalog_hash=t.catalog_hash, seed=t.seed,
        replay=[ReplayStep(sequence=c["sequence"], tool=c["action"]["type"], arguments=c["arguments"],
                           result_references=c.get("result_references", []), result_summary=c["result_summary"],
                           error_code=c.get("error_code"), timestamp=c["timestamp"]) for c in calls],
        score_components=t.score_components,
        kills=[KillOut(rule_id=k["rule_id"], rule_version=k["rule_version"], description=k["description"],
                       evidence=[str(e) for e in k.get("evidence", [])]) for k in t.kills],
        payment_events=t.payment_events, genome={k: v for k, v in t.genome.items() if k != "id"} | {"id": t.genome.get("id")})


def _page(items: list, total: int, offset: int, limit: int) -> dict:
    return {"items": items, "total": total, "offset": offset, "limit": limit}


def world_router(reader: WorldReader, runner: AgentRunner | None = None, ledger_source=lambda: None) -> APIRouter:
    r, runner = APIRouter(), runner or UnconfiguredRunner()

    def gen_out(d: dict) -> GenerationOut:
        c = d.get("config") or {}
        return GenerationOut(generation_id=d["gen_id"], status=d["status"], population_size=d.get("population_size", 0),
                             survivors=d.get("survivors", 0), kills=d.get("kills", 0), seed=c.get("seed"), tasks=c.get("tasks"),
                             catalog_hash=c.get("catalog_hash"), runner=d.get("runner"), error=d.get("error"),
                             published_at=d.get("published_at"))

    @r.post("/agent/run", response_model=AgentRunResult, tags=["agent"])
    def agent_run(req: AgentRunRequest, request: Request):
        out = runner.run(req)
        request.state.cost_usd = None if out.cost_usd is None else str(out.cost_usd)  # surfaced in the structured access log
        return out

    @r.get("/world/generations", response_model=Page[GenerationOut], tags=["world"])
    def generations(offset: Offset = 0, limit: Limit = 50, status: str | None = None):
        rows = sorted((gen_out(d) for d in reader.generations() if status in (None, d["status"])),
                      key=lambda g: (g.published_at or "", g.generation_id), reverse=True)  # newest publish first
        return _page(rows[offset:offset + limit], len(rows), offset, limit)

    @r.get("/world/generations/{generation_id}", response_model=GenerationDetail, tags=["world"])
    def generation(generation_id: str):
        d = next((d for d in reader.generations() if d["gen_id"] == generation_id), None)
        if d is None:
            raise HTTPException(404, "generation_not_found")
        return GenerationDetail(**gen_out(d).model_dump(), summary=d.get("summary") or {})

    @r.get("/world/episodes", response_model=Page[EpisodeOut], tags=["world"])
    def episodes(offset: Offset = 0, limit: Limit = 50, generation_id: str | None = None, agent_id: str | None = None,
                 split: str | None = None, category: str | None = None, killed: bool | None = None,
                 kill_rule_id: str | None = None, min_fitness: float | None = None, max_fitness: float | None = None,
                 sort: str = "-fitness"):
        if sort.lstrip("-") not in EPISODE_SORTS:
            raise HTTPException(422, f"sort must be one of {sorted(EPISODE_SORTS)} (prefix - for descending)")
        f = {k: v for k, v in dict(generation_id=generation_id, agent_id=agent_id, split=split, category=category, killed=killed,
                                   kill_reason=kill_rule_id, min_fitness=min_fitness, max_fitness=max_fitness).items() if v is not None}
        rows, total = reader.traces(f, sort, offset, limit)
        return _page([_episode(t) for t in rows], total, offset, limit)

    @r.get("/world/episodes/{episode_id:path}", response_model=EpisodeDetail, tags=["world"])
    def episode(episode_id: str):
        t = reader.trace(episode_id)
        if t is None:
            raise HTTPException(404, "episode_not_found")
        return _detail(t)

    @r.get("/world/leaderboard", response_model=Page[LeaderboardRow], tags=["world"])
    def leaderboard(generation_id: str | None = None, offset: Offset = 0, limit: Limit = 50):
        gens = {d["gen_id"]: d for d in reader.generations()}
        by: dict[tuple[str, str], list[TraceRecord]] = defaultdict(list)
        for t in reader.all_traces(generation_id):
            by[(t.generation_id, t.agent_id)].append(t)
        rows = []
        for (gid, agent), ts in by.items():
            fit = [t.fitness if t.scored else 0.0 for t in ts]  # an unscored/killed-early episode counts as 0, never skipped
            surv = set(((gens.get(gid) or {}).get("summary") or {}).get("survivors", []))
            rows.append(dict(agent_id=agent, variant=str(ts[0].genome.get("system_prompt_variant", "unknown")), generation_id=gid,
                             episodes=len(ts), mean_fitness=round(sum(fit) / len(fit), 6) if fit else 0.0,
                             killed_episodes=sum(t.killed for t in ts), kill_rules=sorted({t.kill_reason for t in ts if t.kill_reason}),
                             survivor=agent in surv))
        rows.sort(key=lambda x: (x["killed_episodes"] > 0, -x["mean_fitness"], x["agent_id"]))  # agents with any kill rank below clean ones
        return _page([LeaderboardRow(rank=i + 1, **x) for i, x in enumerate(rows)][offset:offset + limit], len(rows), offset, limit)

    @r.get("/world/kills", response_model=Page[KillLogRow], tags=["world"])
    def kills(generation_id: str | None = None, rule_id: str | None = None, offset: Offset = 0, limit: Limit = 50):
        rows = [KillLogRow(episode_id=t.episode_id, agent_id=t.agent_id, generation_id=t.generation_id, task_id=t.task_id,
                           rule_id=k["rule_id"], rule_version=k["rule_version"], evidence=[str(e) for e in k.get("evidence", [])])
                for t in reader.all_traces(generation_id) for k in t.kills if rule_id in (None, k["rule_id"])]
        rows.sort(key=lambda k: (k.generation_id, k.episode_id, k.rule_id))
        return _page(rows[offset:offset + limit], len(rows), offset, limit)

    @r.get("/world/kill-rules", response_model=list[KillRuleOut], tags=["world"])
    def kill_rules():
        counts = Counter(k["rule_id"] for t in reader.all_traces() for k in t.kills)
        return [KillRuleOut(rule_id=x.id, version=x.version, description=x.description, added_on=x.added_on, enabled=x.enabled,
                            kills=counts.get(x.id, 0)) for x in INITIAL_RULES]

    def docs(kind: str, offset: int, limit: int):
        rows, total = reader.documents(kind, offset, limit)
        return _page([DocumentOut(id=str(d.get("id", i)), data={k: v for k, v in d.items() if k != "id"}) for i, d in enumerate(rows)],
                     total, offset, limit)

    @r.get("/models/evaluations", response_model=Page[DocumentOut], tags=["models"])
    def evaluations(offset: Offset = 0, limit: Limit = 50):
        return docs("evaluations", offset, limit)

    @r.get("/models/checkpoints", response_model=Page[DocumentOut], tags=["models"])
    def checkpoints(offset: Offset = 0, limit: Limit = 50):
        return docs("checkpoints", offset, limit)

    @r.get("/payments/ledger", response_model=Page[LedgerRow], tags=["payments"],
           description="Mock-payment events recorded by world runs, or (PAYMENTS_BACKEND=sandbox) this service's sanitized PayPal sandbox calls. Never live money, never credentials.")
    def ledger(generation_id: str | None = None, offset: Offset = 0, limit: Limit = 50):
        live = ledger_source()
        if live is not None:  # PAYMENTS_BACKEND=sandbox: this process's real sandbox calls (sanitized), not world-run mocks
            rows = [LedgerRow(mode="sandbox", episode_id=e.run_id or "", event=e.event, amount=str(e.amount) if e.amount is not None else None,
                              references=[x for x in (e.order_ref, e.capture_ref) if x]) for e in live.entries()]
            return _page(rows[offset:offset + limit], len(rows), offset, limit)
        rows = [LedgerRow(mode="mock", episode_id=t.episode_id, event=e["event"], product_id=e.get("product_id"),
                          amount=e.get("amount"), references=[str(x) for x in e.get("refs", [])])
                for t in reader.all_traces(generation_id) for e in t.payment_events if not e.get("error")]
        rows.sort(key=lambda x: (x.episode_id, x.event))
        return _page(rows[offset:offset + limit], len(rows), offset, limit)

    return r
