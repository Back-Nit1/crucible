"""WebShop adapter: protocol plumbing, honest not-run states, no zero-for-unrun. The fake env/agent test the ADAPTER only;
no number produced here is a WebShop score."""
import datetime as dt
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from agents.model import InferenceError
from eval.contenders import standard_contenders
from eval.webshop import (PINNED_REVISION, Observation, SubprocessWebShopEnv, WebShopBackendError, ModelWebShopAgent, blocked,
                          check_setup, parse_sessions, run_episode, run_webshop)

NOW = dt.datetime(2026, 11, 1, tzinfo=dt.UTC)
C = standard_contenders(model_id="Qwen/Qwen2.5-7B-Instruct", base_revision="a" * 40, prompt_version="p", endpoint="e")[0]


class FakeEnv:
    def __init__(self, rewards, fail_on=()):
        self.rewards, self.fail_on, self.session, self.closed = rewards, set(fail_on), None, False

    def reset(self, session):
        if session in self.fail_on:
            raise WebShopBackendError("boom")
        self.session = session
        return Observation(text="home", instruction=f"buy item {session}", clickables=("buy now",), has_search_bar=True)

    def step(self, action):
        done = action == "click[buy now]"
        return Observation(text="page", clickables=("buy now",)), (self.rewards[self.session] if done else 0.0), done

    def close(self):
        self.closed = True


class Agent:
    def __init__(self, buys=True):
        self.buys, self.seeds = buys, []

    def act(self, *, instruction, observation, history, seed, step):
        self.seeds.append(seed)
        return "click[buy now]" if self.buys and history else "search[x]"


def test_blocked_result_is_not_zero_and_lists_exact_requirements(tmp_path):
    reasons = check_setup(None, None)
    assert reasons and "WEBSHOP_HOME" in reasons[0]
    r = blocked(C, reasons, NOW)
    assert r.status == "blocked_not_run" and r.mean_reward is None and r.score_x100 is None and r.denominator is None
    assert r.webshop_revision == PINNED_REVISION and r.license == "MIT" and any("setup.sh" in c for c in r.setup_commands)


def test_check_setup_requires_pinned_revision_data_index_python_and_java(tmp_path):
    (tmp_path / "data").mkdir()
    out = check_setup(tmp_path, tmp_path / "nopython", which=lambda n: None, git=lambda p: "deadbeef")
    text = " | ".join(out)
    for needle in ("expected " + PINNED_REVISION, "items_shuffle_1000", "search_engine/indexes", "WEBSHOP_PYTHON", "java"):
        assert needle in text
    for rel in ("data/items_shuffle_1000.json", "data/items_ins_v2_1000.json", "data/items_human_ins.json"):
        (tmp_path / rel).write_text("{}")
    (tmp_path / "search_engine" / "indexes").mkdir(parents=True)
    py = tmp_path / "py"
    py.write_text("")
    assert check_setup(tmp_path, py, which=lambda n: "/usr/bin/java", git=lambda p: PINNED_REVISION) == ()


def test_measured_result_has_numerators_denominators_exclusions_and_preserved_seeds(tmp_path):
    env, agent = FakeEnv({0: 1.0, 1: 0.5, 2: 0.0}, fail_on={3}), Agent()
    r = run_webshop(C, agent, env, sessions=(0, 1, 2, 3), seeds=(7, 8), now=NOW, raw_dir=tmp_path)
    assert r.status == "measured" and (r.denominator, r.excluded, r.success_numerator) == (6, 2, 2)
    assert r.mean_reward == Decimal("0.5") and r.score_x100 == Decimal("50") and not r.full_benchmark
    assert {e.seed for e in r.episodes} == {7, 8} and set(agent.seeds) == {7, 8}
    bad = [e for e in r.episodes if e.status == "backend_error"]
    assert len(bad) == 2 and all(e.reward is None for e in bad)             # excluded, never scored 0
    assert all(Path(e.raw_path).is_file() and len(e.raw_sha256) == 64 for e in r.episodes)


def test_agent_that_never_buys_scores_a_real_zero_but_backend_failure_is_not_run():
    r = run_webshop(C, Agent(buys=False), FakeEnv({0: 1.0}), sessions=(0,), seeds=(1,), now=NOW, max_steps=3)
    assert r.status == "measured" and r.mean_reward == 0 and r.episodes[0].status == "step_limit" and r.episodes[0].steps == 3
    n = run_webshop(C, Agent(), FakeEnv({}, fail_on={0}), sessions=(0,), seeds=(1,), now=NOW)
    assert n.status == "blocked_not_run" and n.mean_reward is None and "no WebShop episode ran" in n.not_run_reason


def test_stored_episodes_are_reused_not_rerun_or_double_counted():
    env, agent = FakeEnv({0: 1.0}), Agent()
    first = run_webshop(C, agent, env, sessions=(0,), seeds=(1,), now=NOW)
    calls = len(agent.seeds)
    again = run_webshop(C, agent, env, sessions=(0,), seeds=(1,), now=NOW,
                        done={(e.session, e.seed): e for e in first.episodes})
    assert len(agent.seeds) == calls and again.denominator == 1


def test_parse_sessions():
    assert parse_sessions("0-2,9") == (0, 1, 2, 9)
    with pytest.raises(ValueError):
        parse_sessions("499-500")
    with pytest.raises(ValueError):
        parse_sessions("1,1")


STUB = {
    "gym.py": "class _E:\n    def __init__(self):\n        self.instruction_text = ''\n"
              "    def reset(self, session=None):\n        print('loading noise')\n        self.instruction_text = 'buy %s' % session\n        return 'home', None\n"
              "    def step(self, a):\n        return 'obs:' + a, (1.0 if a == 'click[buy now]' else 0.0), a == 'click[buy now]', None\n"
              "    def get_available_actions(self):\n        return {'has_search_bar': True, 'clickables': ['buy now']}\n"
              "def make(name, **kw):\n    assert name == 'WebAgentTextEnv-v0' and kw['observation_mode'] == 'text'\n    return _E()\n",
    "web_agent_site/__init__.py": "", "web_agent_site/envs/__init__.py": "",
}


def test_driver_protocol_works_over_a_real_subprocess_despite_stdout_noise(tmp_path):
    for rel, text in STUB.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    env = SubprocessWebShopEnv(tmp_path, sys.executable, "1000")
    try:
        obs = env.reset(4)
        assert obs.instruction == "buy 4" and obs.clickables == ("buy now",)
        _, reward, done = env.step("click[buy now]")
        assert (reward, done) == (1.0, True)
    finally:
        env.close()
    dead = SubprocessWebShopEnv(tmp_path, sys.executable, "1000", driver=tmp_path / "missing.py")
    with pytest.raises(WebShopBackendError):
        dead.reset(0)


class Client:
    def __init__(self, raw=None, err=None):
        self.raw, self.err, self.requests = raw, err, []

    def invoke(self, request, retry):
        self.requests.append(request)
        if self.err:
            raise InferenceError(self.err, "x")
        return type("R", (), {"raw_output": self.raw})()


def test_model_agent_pins_the_contender_checkpoint_and_maps_tool_calls():
    client = Client('<tool_call>{"name": "search", "arguments": {"keywords": "red shoes"}}</tool_call>')
    agent = ModelWebShopAgent(client, C)
    obs = Observation(text="t", clickables=("a",), has_search_bar=True)
    assert agent.act(instruction="i", observation=obs, history=(), seed=5, step=0) == "search[red shoes]"
    assert client.requests[0].checkpoint == C.request_checkpoint and client.requests[0].seed == 5
    assert ModelWebShopAgent(Client("garbage"), C).act(instruction="i", observation=obs, history=(), seed=5, step=0) == "invalid[]"
    with pytest.raises(WebShopBackendError):
        ModelWebShopAgent(Client(err="checkpoint_mismatch"), C).act(instruction="i", observation=obs, history=(), seed=5, step=0)
