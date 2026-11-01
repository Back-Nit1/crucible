"""The scheduler must be off by default and only attach a cron when explicitly enabled at deploy time."""
import subprocess
import sys


def schedule_of(env_value):
    code = ("import os,modal_app.world_runner as w;"
            "print(repr(w.SCHEDULE))")
    env = {"PATH": "/usr/bin:/bin"}
    if env_value is not None:
        env["CRUCIBLE_ENABLE_SCHEDULE"] = env_value
    out = subprocess.run([sys.executable, "-W", "ignore", "-c", code], capture_output=True, text=True, env=env,
                         cwd=str(__import__("pathlib").Path(__file__).resolve().parents[1]))
    assert out.returncode == 0, out.stderr[-400:]
    return out.stdout.strip().splitlines()[-1]


def test_schedule_is_off_by_default_and_on_only_with_the_explicit_flag():
    assert schedule_of(None) == "None"
    assert schedule_of("0") == "None"
    assert "Cron" in schedule_of("1") or "cron" in schedule_of("1").lower()
