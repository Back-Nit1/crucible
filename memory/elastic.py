"""Elastic-backed TraceRepository. The leakage filter is part of every query, not post-processing."""
from catalog.providers.elastic import Elastic
from memory import PROTECTED_SPLITS, TraceRecord


def similar_query(vector: list[float], k: int, min_fitness: float) -> dict:
    flt = {"bool": {"filter": [{"term": {"killed": False}}, {"range": {"fitness": {"gte": min_fitness}}}],
                    "must_not": [{"terms": {"split": sorted(PROTECTED_SPLITS)}}]}}
    return {"size": k, "_source": {"excludes": ["embedding"]},
            "knn": {"field": "embedding", "query_vector": vector, "k": k, "num_candidates": max(50, k * 10), "filter": flt}}


class ElasticTraceRepository:
    def __init__(self, es: Elastic, embed=None):
        self.es = es
        self.embed = embed or (lambda t, kind="ingest": es.embed([t], input_type=kind)[0])

    def add(self, trace: TraceRecord) -> None:
        doc = trace.model_dump() | {"embedding": self.embed(trace.task_text)}
        self.es.bulk("traces", [(trace.episode_id, doc)])

    def search(self, task_text: str, k: int, min_fitness: float) -> list[tuple[TraceRecord, float]]:
        body = similar_query(self.embed(task_text, "search"), k, min_fitness)
        hits = self.es.call("POST", f"/{self.es.ix('traces')}/_search", body)["hits"]["hits"]
        return [(TraceRecord(**h["_source"]), float(h.get("_score") or 0.0)) for h in hits]

    def similar(self, task_text: str, k: int = 3, min_fitness: float = 0.0) -> list[TraceRecord]:
        return [t for t, _ in self.search(task_text, k, min_fitness)]
