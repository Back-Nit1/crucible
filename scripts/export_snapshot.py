"""Export one generation's Observatory snapshot as a sample fixture ({"body", "request", "status"} envelope).

  uv run python -m scripts.export_snapshot --env-file "<path>/.env" --generation-id <id> \
      --out docs/api/samples/world_generation_snapshot.json

Goes through the real API route (in-process), so the sample is exactly what /snapshot serves. Exits 2 if > 3 MB."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from scripts._env import load

MAX_BYTES = 3_000_000


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env-file")
    ap.add_argument("--generation-id", required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    if a.env_file:
        load(a.env_file, {"ELASTIC_API_KEY", "ELASTIC_ENDPOINT", "ELASTIC_CLOUD_ID"})
    from fastapi.testclient import TestClient

    from api.main import app
    r = TestClient(app).get(f"/world/generations/{a.generation_id}/snapshot")
    if r.status_code != 200:
        print(f"snapshot failed: HTTP {r.status_code}", file=sys.stderr)
        return 1
    envelope = {"body": r.json(), "request": f"GET /world/generations/{a.generation_id}/snapshot", "status": 200}
    text = json.dumps(envelope, sort_keys=True, separators=(",", ":")) + "\n"
    a.out.write_text(text)
    body = r.json()
    print(f"{len(body['episodes'])} episodes, {len(body['products'])} products, {len(text.encode()):,} bytes -> {a.out}")
    return 2 if len(text.encode()) > MAX_BYTES else 0


if __name__ == "__main__":
    raise SystemExit(main())
