"""WorldReader implementations: Elastic (production) and in-memory (tests, sample data)."""
from __future__ import annotations

from collections import Counter
from itertools import islice
from pydantic import ValidationError

from catalog.providers.elastic import Elastic
from memory import TraceRecord
from api.world import EPISODE_SORTS

MAX_SCAN = 20_000  # dashboards aggregate over at most this many traces; beyond it, results say so via total vs items


def _match(t: TraceRecord, f: dict) -> bool:
    return ((f.get("generation_id") in (None, t.generation_id)) and (f.get("agent_id") in (None, t.agent_id))
            and (f.get("split") in (None, t.split)) and (f.get("category") in (None, t.category))
            and (f.get("killed") in (None, t.killed)) and (f.get("kill_reason") in (None, t.kill_reason))
            and (f.get("min_fitness") is None or (t.scored and t.fitness >= f["min_fitness"]))
            and (f.get("max_fitness") is None or (t.scored and t.fitness <= f["max_fitness"])))


def _key(sort: str):
    field, desc = sort.lstrip("-"), sort.startswith("-")
    assert field in EPISODE_SORTS
    return field, desc


class InMemoryReader:
    def __init__(self, traces=(), generations=(), documents=None):
        self._traces, self._gens, self._docs = list(traces), list(generations), documents or {}

    def generations(self):
        return list(self._gens)

    def traces(self, filters, sort, offset, limit):
        field, desc = _key(sort)
        rows = [t for t in self._traces if _match(t, filters)]
        rows.sort(key=lambda t: (getattr(t, field) if field != "fitness" or t.scored else float("-inf"), t.episode_id), reverse=desc)
        return rows[offset:offset + limit], len(rows)

    def trace(self, episode_id):
        return next((t for t in self._traces if t.episode_id == episode_id), None)

    def all_traces(self, generation_id=None):
        return sorted((t for t in self._traces if generation_id in (None, t.generation_id)), key=lambda t: t.episode_id)

    def trace_generations(self):
        return dict(Counter(t.generation_id for t in self._traces if t.generation_id))

    def documents(self, kind, offset, limit):
        rows = self._docs.get(kind, [])
        return rows[offset:offset + limit], len(rows)


class ElasticReader:
    def __init__(self, es: Elastic):
        self.es = es

    def _query(self, f: dict) -> dict:
        flt = [{"term": {k: f[k]}} for k in ("generation_id", "agent_id", "split", "category", "killed", "kill_reason") if k in f]
        rng = {op: f[k] for k, op in (("min_fitness", "gte"), ("max_fitness", "lte")) if k in f}
        if rng:
            flt += [{"range": {"fitness": rng}}, {"term": {"scored": True}}]
        return {"bool": {"filter": flt}} if flt else {"match_all": {}}

    @staticmethod
    def _parse(hits) -> list[TraceRecord]:
        out = []
        for h in hits:
            try:
                out.append(TraceRecord(**h))
            except (ValidationError, TypeError):
                continue  # malformed documents are never shown
        return out

    def generations(self):
        out = self.es.call("POST", f"/{self.es.ix('generations')}/_search", {"size": 1000, "query": {"match_all": {}}})
        return [h["_source"] for h in out["hits"]["hits"]]

    def traces(self, filters, sort, offset, limit):
        field, desc = _key(sort)
        body = {"from": offset, "size": limit, "track_total_hits": True, "query": self._query(filters),
                "_source": {"excludes": ["embedding"]},
                "sort": [{field: {"order": "desc" if desc else "asc", "unmapped_type": "keyword"}}, {"episode_id": "asc"}]}
        out = self.es.call("POST", f"/{self.es.ix('traces')}/_search", body)["hits"]
        return self._parse(h["_source"] for h in out["hits"]), out["total"]["value"]

    def trace(self, episode_id):
        body = {"size": 1, "query": {"term": {"episode_id": episode_id}}, "_source": {"excludes": ["embedding"]}}
        hits = self.es.call("POST", f"/{self.es.ix('traces')}/_search", body)["hits"]["hits"]
        return (self._parse(h["_source"] for h in hits) or [None])[0]

    def all_traces(self, generation_id=None):
        q = {"term": {"generation_id": generation_id}} if generation_id else {"match_all": {}}
        return self._parse(src for src, _ in islice(self.es.scan("traces", q, "episode_id"), MAX_SCAN))

    def trace_generations(self):
        """generation id -> episode count, straight from the traces index (includes runs not yet published)."""
        body = {"size": 0, "aggs": {"g": {"terms": {"field": "generation_id", "size": 1000}}}}
        out = self.es.call("POST", f"/{self.es.ix('traces')}/_search", body)
        return {b["key"]: b["doc_count"] for b in out["aggregations"]["g"]["buckets"] if b["key"]}

    def documents(self, kind, offset, limit):
        try:
            out = self.es.call("POST", f"/{self.es.ix(kind)}/_search", {"from": offset, "size": limit, "track_total_hits": True, "query": {"match_all": {}}})["hits"]
        except Exception:
            return [], 0  # index not created yet (no evaluations/checkpoints published): an empty page, not an error
        return [{"id": h["_id"], **h["_source"]} for h in out["hits"]], out["total"]["value"]
