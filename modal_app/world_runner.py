"""Headless, resumable world generations on Modal (CPU only, MockPayments only).

Run one generation (idempotent: rerunning the same id resumes / no-ops once complete):
  CRUCIBLE_ENV_FILE=<.env> uv run modal run modal_app/world_runner.py --action run --generation-id remote-smoke --population 6 --tasks 4
Inspect:  ... --action status          Resume the latest unfinished one:  ... --action resume
Schedule (OFF unless explicitly enabled at deploy time; `modal run` never activates schedules):
  CRUCIBLE_ENABLE_SCHEDULE=1 CRUCIBLE_ENV_FILE=<.env> uv run modal deploy modal_app/world_runner.py
Disable:  uv run modal app stop crucible-world      (or redeploy without CRUCIBLE_ENABLE_SCHEDULE=1)

Checkpoints live on the `crucible-world-checkpoints` Volume; traces go to Elastic; the Elastic key is sent to Modal as a
per-run secret read from your environment (never stored in the repo, never printed). Scheduled runs only RESUME the latest
unfinished generation: they never start a new (paid) one. Overlap is prevented by max_containers=1 plus the store lease."""
from __future__ import annotations

import json
import os
from pathlib import Path

import modal

APP_NAME = "crucible-world"
VOLUME_ROOT = "/vol"
SOURCES = ["catalog", "payments", "memory", "tasks", "agents", "scoring", "world", "training", "eval"]


def _load_env_file() -> None:  # local only: lets the secret above pick values up without putting them on a command line
    path = os.environ.get("CRUCIBLE_ENV_FILE")
    if path:
        for line in Path(path).read_text().splitlines():
            k, _, v = line.partition("=")
            if k.strip() in {"ELASTIC_API_KEY", "ELASTIC_CLOUD_ID", "ELASTIC_ENDPOINT"} and v.strip():
                os.environ[k.strip()] = v.strip().strip("\"'")


_load_env_file()
SECRET_KEYS = [k for k in ("ELASTIC_API_KEY", "ELASTIC_CLOUD_ID", "ELASTIC_ENDPOINT") if os.environ.get(k)]

image = (modal.Image.debian_slim(python_version="3.12").pip_install("pydantic==2.14.2", "pyyaml>=6", "httpx>=0.27")
         .env({"CRUCIBLE_MANIFEST_DIR": "/manifests"})
         .add_local_dir("data/manifests", remote_path="/manifests", copy=True)
         .add_local_python_source(*SOURCES))
volume = modal.Volume.from_name("crucible-world-checkpoints", create_if_missing=True, version=2)
app = modal.App(APP_NAME)
secrets = [modal.Secret.from_local_environ(SECRET_KEYS)] if SECRET_KEYS else []
FUNCTION = dict(image=image, volumes={VOLUME_ROOT: volume}, secrets=secrets, cpu=1.0, memory=1024, timeout=3600,
                max_containers=1, retries=0)


def _store():
    from world.store import FileBlobStore, GenerationStore
    return GenerationStore(FileBlobStore(f"{VOLUME_ROOT}/generations", after_write=volume.commit, before_read=volume.reload))


def _job(generation_id: str | None, seed: int, population: int, tasks: int, max_episodes: int | None, resume_latest: bool) -> dict:
    import time

    from catalog.cache import FrozenCache
    from catalog.providers.elastic import Elastic, ElasticCatalogProvider, endpoint_from_cloud_id, load_manifest_hashes
    from memory.elastic import ElasticTraceRepository
    from world import report
    from world.remote import approx_cost_usd, latest_unfinished
    from world.runtime import audit_and_curate, build_population, run_generation
    from world.taskgen import generate_tasks

    store = _store()
    if resume_latest:
        generation_id = latest_unfinished(store)
        if generation_id is None:
            return {"status": "nothing_to_resume"}
        saved = json.loads(Path(f"{VOLUME_ROOT}/generations/params-{generation_id}.json").read_text())
        seed, population, tasks = saved["seed"], saved["population"], saved["tasks"]
    assert generation_id, "generation id required"
    params_path = Path(f"{VOLUME_ROOT}/generations/params-{generation_id}.json")
    params_path.parent.mkdir(parents=True, exist_ok=True)
    params_path.write_text(json.dumps({"seed": seed, "population": population, "tasks": tasks}))
    es = Elastic(os.environ.get("ELASTIC_ENDPOINT") or endpoint_from_cloud_id(os.environ["ELASTIC_CLOUD_ID"]))
    es.update_traces_mapping()
    catalog, manifests, traces = FrozenCache(ElasticCatalogProvider(es)), load_manifest_hashes(), ElasticTraceRepository(es)
    t0 = time.monotonic()
    task_set, genomes = generate_tasks(catalog, manifests, seed=seed, count=tasks), build_population(population, seed)
    res = run_generation(generation_id=generation_id, seed=seed, genomes=genomes, tasks=task_set, manifests=manifests,
                         catalog=catalog, store=store, traces=traces, max_episodes=max_episodes, owner="modal-world-runner",
                         log=print)
    out = {"generation_id": generation_id, "status": res.state.status.value, "executed_this_run": len(res.executed),
           "remaining": len(res.state.remaining())}
    if res.complete:
        eps, props, cur, nxt = audit_and_curate(result=res, tasks=task_set, genomes=genomes, traces=traces, catalog=catalog,
                                                manifests=manifests, breed_seed=seed)
        s = report.summarize(result=res, tasks=task_set, episodes=eps, proposals=props, curated=cur, next_pop=nxt,
                             params={"seed": seed, "population": population, "tasks": tasks, "model": "scripted",
                                     "payments": "mock", "provider": "elastic_snapshot", "runner": "modal"})
        report.write(s, f"{VOLUME_ROOT}/reports/{generation_id}")
        from training.rollouts import write_rollouts
        write_rollouts(f"{VOLUME_ROOT}/reports/{generation_id}/rollouts.jsonl", eps, tasks={t.id: t for t in task_set},
                       genomes={g.id: g for g in genomes}, catalog=catalog, policy_id=res.state.compat.policy_id)
        Path(f"{VOLUME_ROOT}/reports/{generation_id}/curation_report.json").write_text(json.dumps(cur.drop_report(), indent=1))
        from world.publish import publish_generation, publish_kill_rules
        publish_generation(es, res.state, s, runner="modal")
        publish_kill_rules(es, s["kills"]["by_rule"])
        out |= {"episodes": s["episodes"], "kills": s["kills"]["by_rule"], "survivors": len(s["survivors"]), "safety": s["safety"],
                "sft_records": len(cur.records)}
    out["cost"] = approx_cost_usd(time.monotonic() - t0)
    ledger = Path(f"{VOLUME_ROOT}/cost.jsonl")
    ledger.open("a").write(json.dumps({"generation_id": generation_id, **out["cost"]}) + "\n")
    volume.commit()
    return out


@app.function(**FUNCTION)
def run_remote(generation_id: str | None = None, seed: int = 20261101, population: int = 6, tasks: int = 4,
               max_episodes: int | None = None, resume_latest: bool = False) -> dict:
    return _job(generation_id, seed, population, tasks, max_episodes, resume_latest)


SCHEDULE = (modal.Cron(os.environ.get("CRUCIBLE_SCHEDULE_CRON", "0 * * * *"))
            if os.environ.get("CRUCIBLE_ENABLE_SCHEDULE") == "1" else None)  # None = no recurring job exists


@app.function(**FUNCTION, schedule=SCHEDULE)
def scheduled_resume() -> dict:
    """Resumes the latest unfinished generation. Inert (no schedule attached) unless CRUCIBLE_ENABLE_SCHEDULE=1 at deploy."""
    return _job(None, 0, 0, 0, None, True)


@app.function(image=image, volumes={VOLUME_ROOT: volume}, cpu=0.125, memory=256, timeout=120)
def status_remote() -> dict:
    from world.remote import status
    volume.reload()
    ledger = Path(f"{VOLUME_ROOT}/cost.jsonl")
    rows = [json.loads(line) for line in ledger.read_text().splitlines()] if ledger.exists() else []
    return {"generations": status(_store()), "approx_total_usd": round(sum(r["total_usd"] for r in rows), 6), "runs": len(rows)}


@app.local_entrypoint()
def main(action: str = "status", generation_id: str = "", seed: int = 20261101, population: int = 6, tasks: int = 4,
         max_episodes: int = 0):
    if action == "status":
        print(json.dumps(status_remote.remote(), indent=1))
    elif action == "run":
        if not generation_id:
            raise SystemExit("--generation-id is required for run")
        print(json.dumps(run_remote.remote(generation_id, seed, population, tasks, max_episodes or None), indent=1))
    elif action == "resume":
        print(json.dumps(run_remote.remote(resume_latest=True), indent=1))
    elif action == "disable":
        print("uv run modal app stop crucible-world   # or redeploy without CRUCIBLE_ENABLE_SCHEDULE=1")
    else:
        raise SystemExit("action must be one of: run, status, resume, disable")
