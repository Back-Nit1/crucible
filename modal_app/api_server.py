"""The Crucible API (FastAPI) hosted on Modal, so nothing but a browser runs on your machine. CPU only, scales to zero.

  CRUCIBLE_ENV_FILE=<.env> CORS_ALLOW_ORIGINS=http://localhost:3000 uv run modal deploy modal_app/api_server.py
  # prints https://<workspace>--crucible-api-web.modal.run ; point the web at it:
  cd web && NEXT_PUBLIC_API_BASE_URL=https://<that url> NEXT_PUBLIC_DATA_MODE=live npm run dev
  uv run modal app stop crucible-api      # stop it

Cost: CPU-only (0.5 core, 1 GB) and min_containers=0, so idle costs $0; one container serves many requests and the
Observatory's live streams. The Elastic and PayPal sandbox keys reach Modal as a secret built from your environment
(read from CRUCIBLE_ENV_FILE, never stored in the repo or printed). Live training progress is read from the
`crucible-live-training` Modal Dict without extra credentials, because this app runs inside the same workspace."""
from __future__ import annotations

import os
from pathlib import Path

import modal

APP_NAME = "crucible-api"
SOURCES = ["api", "agents", "catalog", "eval", "memory", "modal_app", "payments", "scoring", "scripts", "tasks", "training", "world"]
SECRET_NAMES = ("ELASTIC_API_KEY", "ELASTIC_CLOUD_ID", "ELASTIC_ENDPOINT", "PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET",
                "PAYPAL_ENV", "PAYMENTS_BACKEND", "PAYPAL_RETURN_URL", "PAYPAL_CANCEL_URL")


def _load_env_file() -> None:  # local only, at deploy time
    path = os.environ.get("CRUCIBLE_ENV_FILE")
    if path:
        for line in Path(path).read_text().splitlines():
            k, _, v = line.partition("=")
            if k.strip() in SECRET_NAMES and v.strip() and not os.environ.get(k.strip()):
                os.environ[k.strip()] = v.strip().strip("\"'")


_load_env_file()
secrets = [modal.Secret.from_local_environ([k for k in SECRET_NAMES if os.environ.get(k)])]
image = (modal.Image.debian_slim(python_version="3.12")
         .pip_install("fastapi==0.162.0", "httpx==0.28.1", "jsonschema==4.26.0", "pydantic==2.14.2", "pyyaml==6.0.3")
         .env({"DEMO_MODE": "1", "CRUCIBLE_LIVE_TRAINING": "modal",
               "CORS_ALLOW_ORIGINS": os.environ.get("CORS_ALLOW_ORIGINS", "http://localhost:3000")})
         .add_local_dir("config", "/root/config", copy=True)
         .add_local_dir("data/manifests", "/root/data/manifests", copy=True)
         .add_local_dir("docs", "/root/docs", copy=True, ignore=["**/*.png", "**/*.svg", "**/*.gif", "**/*.mp4"])
         .add_local_python_source(*SOURCES))
app = modal.App(APP_NAME)


@app.function(image=image, secrets=secrets, cpu=0.5, memory=1024, min_containers=0, scaledown_window=300, timeout=3600)
@modal.concurrent(max_inputs=100)  # one container serves many requests and SSE streams
@modal.asgi_app()
def web():
    from api.main import app as api
    return api
