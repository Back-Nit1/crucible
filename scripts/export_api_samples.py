"""Write real sample API responses (from the live Elastic trace store) for frontend development: docs/api/samples/*.json.
  uv run python -m scripts.export_api_samples --env-file <.env> [--generation-id gen-20261101-p8-t12]
Pages are truncated to 3 items; nothing here contains credentials (the API never returns them)."""
import argparse
import json
from pathlib import Path

from scripts._env import load


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file", required=True)
    ap.add_argument("--generation-id", default="gen-20261101-p8-t12")
    ap.add_argument("--out", default="docs/api/samples")
    a = ap.parse_args(argv)
    load(a.env_file, {"ELASTIC_API_KEY", "ELASTIC_ENDPOINT", "ELASTIC_CLOUD_ID"})
    from fastapi.testclient import TestClient

    from api.main import create_app, default_reader
    c = TestClient(create_app(reader=default_reader()))
    g = a.generation_id
    ep = c.get("/world/episodes", params={"generation_id": g, "limit": 3, "sort": "-fitness"}).json()
    killed = c.get("/world/episodes", params={"generation_id": g, "killed": True, "limit": 1}).json()["items"][0]["episode_id"]
    calls = {"health": "/health", "world_generations": "/world/generations", "world_generation_detail": f"/world/generations/{g}",
             "world_episodes": f"/world/episodes?generation_id={g}&limit=3&sort=-fitness",
             "world_episode_detail": f"/world/episodes/{ep['items'][0]['episode_id']}",
             "world_episode_detail_killed": f"/world/episodes/{killed}",
             "world_leaderboard": f"/world/leaderboard?generation_id={g}", "world_kills": f"/world/kills?generation_id={g}&limit=3",
             "world_kill_rules": "/world/kill-rules", "models_evaluations": "/models/evaluations",
             "models_checkpoints": "/models/checkpoints", "payments_ledger": f"/payments/ledger?generation_id={g}&limit=3"}
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, path in calls.items():
        r = c.get(path)
        body = r.json()
        if isinstance(body, dict) and "items" in body:
            body["items"] = body["items"][:3]
        (out / f"{name}.json").write_text(json.dumps({"request": f"GET {path}", "status": r.status_code, "body": body}, indent=2, sort_keys=True) + "\n")
        print(r.status_code, path)


if __name__ == "__main__":
    main()
