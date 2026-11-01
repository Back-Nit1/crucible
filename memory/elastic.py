"""Elastic-backed TraceRepository. The leakage filter is part of every query, not post-processing."""
from pydantic import ValidationError

from catalog.providers.elastic import Elastic
from memory import PROTECTED_SPLITS, TraceRecord, eligible


def similar_query(vector: list[float], k: int, min_fitness: float) -> dict:
    flt = {"bool": {"filter": [{"term": {"killed": False}}, {"term": {"scored": True}},
                              {"range": {"fitness": {"gte": min_fitness}}}],
                    "must_not": [{"terms": {"split": list(PROTECTED_SPLITS)}}]}}
    return {"size": k, "_source": {"excludes": ["embedding"]},
            "knn": {"field": "embedding", "query_vector": vector, "k": k, "num_candidates": max(50, k * 10), "filter": flt}}


class ElasticTraceRepository:
    def __init__(self, es: Elastic, embed=None):
        self.es = es
        self.embed = embed or (lambda t, kind="ingest": es.embed([t], input_type=kind)[0])

    def add(self, trace: TraceRecord) -> None:
        doc = trace.model_dump() | {"embedding": self.embed(trace.task_text)}
        self.es.bulk("traces", [(trace.episode_id, doc)])

    def similar(self, task_text: str, k: int = 3, min_fitness: float = 0.0) -> list[TraceRecord]:
        """Filtered kNN; every hit is re-validated and re-filtered client-side, malformed hits are dropped (fail closed)."""
        body = similar_query(self.embed(task_text, "search"), k, min_fitness)
        hits = self.es.call("POST", f"/{self.es.ix('traces')}/_search", body)["hits"]["hits"]
        out = []
        for h in hits:
            try:
                t = TraceRecord(**h["_source"])
            except (ValidationError, TypeError, KeyError):
                continue
            if eligible(t, min_fitness):
                out.append(t)
        return out

    def by_generation(self, generation_id: str) -> list[TraceRecord]:
        """Dashboard/audit path: all traces of a generation, every split. Malformed docs are skipped (and counted by callers
        through the length mismatch against the checkpoint)."""
        out = []
        for src, _ in self.es.scan("traces", {"term": {"generation_id": generation_id}}, "episode_id"):
            try:
                out.append(TraceRecord(**src))
            except (ValidationError, TypeError):
                continue
        return out
