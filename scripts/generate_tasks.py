"""Generate real tasks from the live frozen snapshot through ProviderRouter(mode="training").
  uv run python -m scripts.generate_tasks --env-file .env --per-category 12 --seed 20261101 --out data/tasks/tasks_v1.json
Writes the TaskSpec list plus a manifest (counts by split/impossible, catalog hash per category). Reads only; no payments."""
import argparse
import hashlib
import json
import os
from collections import Counter
from pathlib import Path

from catalog.providers.elastic import Elastic, ElasticCatalogProvider, endpoint_from_cloud_id
from catalog.router import ProviderRouter
from catalog.taskgen import generate_tasks
from catalog.training import TrainingCatalog
from scripts._env import load

CATEGORIES = ["Sports_and_Outdoors", "Electronics", "Office_Products", "Clothing_Shoes_and_Jewelry"]


def training_catalog(env_file: str | None = None) -> TrainingCatalog:
    if env_file:
        load(env_file, {"ELASTIC_API_KEY", "ELASTIC_ENDPOINT", "ELASTIC_CLOUD_ID"})
    es = Elastic(os.environ.get("ELASTIC_ENDPOINT") or endpoint_from_cloud_id(os.environ["ELASTIC_CLOUD_ID"]))
    cfg = {"live_chat": "elastic_snapshot", "providers": {"elastic_snapshot": {"enabled": True, "reviews_source": "amazon2023"}}}
    return TrainingCatalog(ProviderRouter({"elastic_snapshot": ElasticCatalogProvider(es)}, cfg), mode="training")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file")
    ap.add_argument("--per-category", type=int, default=12)
    ap.add_argument("--seed", type=int, default=20261101)
    ap.add_argument("--out", default="data/tasks/tasks_v1.json")
    a = ap.parse_args()
    cat = training_catalog(a.env_file)
    manifests = {c: json.loads(Path(f"data/manifests/{c}.json").read_text())["sha256"] for c in CATEGORIES}
    snapshot_id = "amazon2023-" + hashlib.sha256(json.dumps(manifests, sort_keys=True).encode()).hexdigest()[:12]
    tasks = generate_tasks(cat, CATEGORIES, a.per_category, a.seed, snapshot_id)
    doc = {"snapshot_id": snapshot_id, "category_manifests": manifests, "seed": a.seed,
           "counts": {"tasks": len(tasks), "impossible": sum(t.is_impossible for t in tasks),
                      "by_split": dict(Counter(t.split.value for t in tasks)),
                      "unsuitable": sum(not t.suitable_for_deterministic_training for t in tasks)},
           "tasks": [t.model_dump(mode="json") for t in tasks]}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    print(json.dumps({k: v for k, v in doc.items() if k != "tasks"}, indent=1))


if __name__ == "__main__":
    main()
