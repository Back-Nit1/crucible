"""WebShop (Yao et al., 2022) benchmark adapter.

Official source: https://github.com/princeton-nlp/WebShop (MIT license, verified 2026-11-01), pinned to the revision below.
Benchmark method, taken from that revision's baseline_models/test.py: for session i in range(500): env.reset(session=i);
up to 100 actions of the form search[...] / click[...]; the final reward in [0, 1] is returned when the agent clicks
'Buy Now' (the paper reports reward x 100). Nothing from WebShop (code, data, index, trajectories) is vendored here: the
benchmark runs in its own interpreter, set up by the user, and talks to this module through eval.webshop_driver.

A WebShop result is `measured` only if episodes really ran. Anything else is `blocked_not_run` with the exact unmet
requirements: a score of 0 is never used as a stand-in for "not run"."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import shutil
import subprocess
from collections.abc import Callable, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from eval.contenders import ContenderConfig

WEBSHOP_REPO = "https://github.com/princeton-nlp/WebShop"
PINNED_REVISION = "64fa2a5c15c7daa698b9ac93f5bb5437b634c9bd"   # master HEAD observed 2026-11-01
LICENSE = "MIT"
BENCHMARK_SESSIONS = 500       # baseline_models/test.py: for i in range(500)
MAX_STEPS = 100                # baseline_models/test.py: for i in range(100) per episode
RESULT_VERSION = "webshop-result-1.0"
REQUIRED_DATA = ("data/items_shuffle_1000.json", "data/items_ins_v2_1000.json", "data/items_human_ins.json")
SETUP_COMMANDS = (
    f"git clone {WEBSHOP_REPO} \"$WEBSHOP_HOME\" && git -C \"$WEBSHOP_HOME\" checkout {PINNED_REVISION}",
    "conda create -n webshop python=3.8.13 && conda activate webshop      # Apple silicon: follow README_INSTALL_ARM-MAC.md",
    "cd \"$WEBSHOP_HOME\" && ./setup.sh -d small      # installs deps, downloads data via gdown, builds the search index (needs JDK 11)",
    "export WEBSHOP_HOME=<clone dir> WEBSHOP_PYTHON=<conda env python>   # then re-run scripts.run_evaluation --webshop-sessions 0-49",
)


class WebShopNotRunnable(RuntimeError):
    def __init__(self, reasons: Sequence[str]):
        self.reasons = tuple(reasons)
        super().__init__("; ".join(self.reasons))


class WebShopBackendError(RuntimeError):
    """The model or the benchmark process failed: the episode did not run and is excluded, not scored zero."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Observation(_Strict):
    text: str
    instruction: str | None = None
    clickables: tuple[str, ...] = ()
    has_search_bar: bool = False


class WebShopEnv(Protocol):
    def reset(self, session: int) -> Observation: ...
    def step(self, action: str) -> tuple[Observation, float, bool]: ...
    def close(self) -> None: ...


class WebShopAgent(Protocol):
    def act(self, *, instruction: str, observation: Observation, history: tuple[str, ...], seed: int, step: int) -> str: ...


class EpisodeResult(_Strict):
    session: int
    seed: int
    status: Literal["completed", "step_limit", "backend_error"]
    steps: int
    reward: Decimal | None            # None = not run (backend_error); 0 only when the agent really ended without buying
    instruction: str | None = None
    error: str | None = None
    raw_sha256: str                   # hash of the full transcript, kept in `raw_path`; transcripts are not committed
    raw_path: str | None = None


class WebShopResult(_Strict):
    result_version: str = RESULT_VERSION
    status: Literal["measured", "blocked_not_run"]
    contender_id: str
    contender_identity_hash: str
    webshop_repo: str = WEBSHOP_REPO
    webshop_revision: str = PINNED_REVISION
    license: str = LICENSE
    benchmark_sessions_total: int = BENCHMARK_SESSIONS
    sessions: tuple[int, ...] = ()
    seeds: tuple[int, ...] = ()
    max_steps: int = MAX_STEPS
    episodes: tuple[EpisodeResult, ...] = ()
    success_numerator: int | None = None          # reward == 1 (perfect attribute/option/price match)
    denominator: int | None = None                # episodes that actually ran
    excluded: int | None = None                   # backend errors
    mean_reward: Decimal | None = None            # [0, 1]; paper score = x100
    score_x100: Decimal | None = None
    full_benchmark: bool = False                  # True only when all 500 sessions ran: otherwise NOT comparable to published scores
    not_run_reason: str | None = None
    unmet_requirements: tuple[str, ...] = ()
    setup_commands: tuple[str, ...] = SETUP_COMMANDS
    created_at: dt.datetime


def blocked(contender: ContenderConfig, reasons: Sequence[str], now: dt.datetime) -> WebShopResult:
    return WebShopResult(status="blocked_not_run", contender_id=contender.id, contender_identity_hash=contender.identity_hash,
                         not_run_reason="; ".join(reasons), unmet_requirements=tuple(reasons), created_at=now)


def check_setup(home: str | Path | None, python: str | Path | None, *, which: Callable[[str], str | None] = shutil.which,
                git: Callable[[Path], str | None] | None = None) -> tuple[str, ...]:
    """Every unmet requirement for running the pinned benchmark locally; empty means runnable."""
    missing: list[str] = []
    if not home or not Path(home).is_dir():
        return ("WEBSHOP_HOME is not set to a clone of " + WEBSHOP_REPO,)
    root = Path(home)
    head = (git or _git_head)(root)
    if head != PINNED_REVISION:
        missing.append(f"WebShop checkout is at {head or 'an unknown revision'}, expected {PINNED_REVISION}")
    missing += [f"missing {rel} (run ./setup.sh -d small)" for rel in REQUIRED_DATA if not (root / rel).is_file()]
    if not (root / "search_engine" / "indexes").is_dir():
        missing.append("missing search_engine/indexes (setup.sh builds it; needs JDK 11)")
    if not python or not Path(python).is_file():
        missing.append("WEBSHOP_PYTHON is not set to the Python 3.8 interpreter of the webshop environment")
    if which("java") is None:
        missing.append("java not found on PATH (search engine indexing/serving needs a JDK)")
    return tuple(missing)


def _git_head(root: Path) -> str | None:
    try:
        return subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


class SubprocessWebShopEnv:
    """Talks JSONL to eval.webshop_driver running under the WebShop interpreter (cwd = the WebShop clone)."""

    def __init__(self, home: str | Path, python: str | Path, num_products: str = "1000", driver: str | Path | None = None):
        driver = driver or Path(__file__).with_name("webshop_driver.py")
        self.proc = subprocess.Popen([str(python), str(driver), num_products], cwd=str(home), stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)

    def _call(self, **msg) -> dict:
        if self.proc.poll() is not None:
            raise WebShopBackendError("WebShop process exited")
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            raise WebShopBackendError("WebShop process closed its output")
        reply = json.loads(line)
        if not reply.get("ok"):
            raise WebShopBackendError(str(reply.get("error")))
        return reply

    @staticmethod
    def _obs(reply: dict) -> Observation:
        avail = reply.get("available") or {}
        return Observation(text=reply["observation"], instruction=reply.get("instruction"),
                           clickables=tuple(avail.get("clickables", ())), has_search_bar=bool(avail.get("has_search_bar")))

    def reset(self, session: int) -> Observation:
        return self._obs(self._call(cmd="reset", session=session))

    def step(self, action: str):
        reply = self._call(cmd="step", action=action)
        return self._obs(reply), float(reply["reward"]), bool(reply["done"])

    def close(self) -> None:
        try:
            self._call(cmd="close")
        except Exception:
            pass
        self.proc.kill()


def run_episode(env: WebShopEnv, agent: WebShopAgent, *, session: int, seed: int, max_steps: int = MAX_STEPS,
                raw_dir: Path | None = None) -> EpisodeResult:
    transcript: list[dict] = []
    status, reward, error, instruction, steps = "step_limit", Decimal(0), None, None, 0
    try:
        obs = env.reset(session)
        instruction = obs.instruction
        if not instruction:
            raise WebShopBackendError("benchmark returned no instruction")
        transcript.append({"observation": obs.text, "instruction": instruction})
        history: list[str] = []
        for step in range(max_steps):
            action = agent.act(instruction=instruction, observation=obs, history=tuple(history), seed=seed, step=step)
            obs, step_reward, done = env.step(action)
            history.append(action)
            steps = step + 1
            transcript.append({"action": action, "reward": step_reward, "done": done, "observation": obs.text})
            if done:
                status, reward = "completed", Decimal(str(step_reward))
                break
    except (WebShopBackendError, RuntimeError, OSError, ValueError) as exc:
        status, reward, error = "backend_error", None, f"{type(exc).__name__}: {exc}"
    raw = json.dumps(transcript, sort_keys=True)
    path = None
    if raw_dir is not None:
        from eval.runner import atomic_write
        target = Path(raw_dir) / f"{session}__{seed}.json"
        atomic_write(target, raw + "\n")
        path = str(target)
    return EpisodeResult(session=session, seed=seed, status=status, steps=steps, reward=reward, instruction=instruction,
                         error=error, raw_sha256=hashlib.sha256(raw.encode()).hexdigest(), raw_path=path)


def aggregate(contender: ContenderConfig, episodes: Sequence[EpisodeResult], sessions: Sequence[int], seeds: Sequence[int],
              now: dt.datetime) -> WebShopResult:
    ran = [e for e in episodes if e.status != "backend_error"]
    if not ran:
        return blocked(contender, ["no WebShop episode ran: " + (episodes[0].error if episodes and episodes[0].error else "no episodes")], now)
    mean = sum((e.reward for e in ran), Decimal(0)) / len(ran)
    return WebShopResult(
        status="measured", contender_id=contender.id, contender_identity_hash=contender.identity_hash, sessions=tuple(sessions),
        seeds=tuple(seeds), episodes=tuple(episodes), success_numerator=sum(e.reward == 1 for e in ran), denominator=len(ran),
        excluded=len(episodes) - len(ran), mean_reward=mean, score_x100=mean * 100,
        full_benchmark=sorted(set(sessions)) == list(range(BENCHMARK_SESSIONS)) and len(ran) == len(episodes), created_at=now)


def run_webshop(contender: ContenderConfig, agent: WebShopAgent, env: WebShopEnv, *, sessions: Sequence[int], seeds: Sequence[int],
                now: dt.datetime, raw_dir: Path | None = None, max_steps: int = MAX_STEPS,
                done: dict[tuple[int, int], EpisodeResult] | None = None) -> WebShopResult:
    """Every (session, seed) once; `done` (previously stored episodes) are reused, never re-run or double-counted."""
    episodes = []
    for seed in seeds:
        for session in sessions:
            prior = (done or {}).get((session, seed))
            episodes.append(prior if prior is not None and prior.status != "backend_error"
                            else run_episode(env, agent, session=session, seed=seed, max_steps=max_steps, raw_dir=raw_dir))
    return aggregate(contender, episodes, sessions, seeds, now)


SEARCH = {"name": "search", "description": "Search the shop for keywords.", "parameters": {
    "type": "object", "properties": {"keywords": {"type": "string"}}, "required": ["keywords"], "additionalProperties": False}}
CLICK = {"name": "click", "description": "Click one of the listed clickable elements, using its exact text.", "parameters": {
    "type": "object", "properties": {"value": {"type": "string"}}, "required": ["value"], "additionalProperties": False}}
WEBSHOP_PROMPT = ("You are shopping on a website to satisfy an instruction. Respond with exactly one tool call per turn: search "
                  "with keywords, or click an element from the provided clickables. Buy only when a product matches the "
                  "instruction's attributes, options and price limit, by clicking 'buy now'.")


class ModelWebShopAgent:
    """Maps a configured Crucible contender onto the benchmark's action space through the same pinned inference client.

    `client.invoke(ModelRequest, retry)` is the public Qwen client interface (agents.qwen_client); every request pins the
    contender's checkpoint, so a client that cannot serve it raises instead of silently answering with the base model."""

    def __init__(self, client, contender: ContenderConfig):
        self.client, self.contender = client, contender

    def act(self, *, instruction: str, observation: Observation, history: tuple[str, ...], seed: int, step: int) -> str:
        from agents.model import InferenceError, Message, ModelRequest, ToolDefinition, _native_calls
        content = (f"Instruction: {instruction}\n\nPage:\n{observation.text}\n\nClickables: {list(observation.clickables)}"
                   f"\nSearch bar: {'yes' if observation.has_search_bar else 'no'}\nPrevious actions: {list(history[-8:])}")
        request = ModelRequest(request_id=f"webshop:{self.contender.id}:{seed}", sequence=step, system_prompt=WEBSHOP_PROMPT,
                               messages=(Message(role="user", content=content),),
                               tools=(ToolDefinition(**SEARCH), ToolDefinition(**CLICK)), seed=seed,
                               temperature=self.contender.temperature, checkpoint=self.contender.request_checkpoint)
        try:
            response = self.client.invoke(request, 0)
        except InferenceError as exc:
            raise WebShopBackendError(f"inference failed: {exc.code}") from None
        try:
            call = _native_calls(response.raw_output)[0]
            if call.name == "search":
                return f"search[{call.arguments['keywords']}]"
            if call.name == "click":
                return f"click[{call.arguments['value']}]"
        except (ValueError, KeyError, TypeError):
            pass
        return "invalid[]"  # the benchmark treats an unparsable action as a no-op: a real, scored model failure


def parse_sessions(spec: str) -> tuple[int, ...]:
    """'0-49' or '0,5,9'."""
    out: list[int] = []
    for part in spec.split(","):
        lo, dash, hi = part.partition("-")
        out.extend(range(int(lo), int(hi) + 1) if dash else [int(lo)])
    if not out or any(not 0 <= s < BENCHMARK_SESSIONS for s in out) or len(out) != len(set(out)):
        raise ValueError(f"sessions must be unique integers in [0, {BENCHMARK_SESSIONS})")
    return tuple(out)
