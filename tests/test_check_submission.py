"""scripts/check_submission.py on throwaway git repos with a fake `gh`."""
import datetime as dt
import json
import subprocess

from scripts import check_submission as cs

OK_GH = lambda *a: json.dumps({"licenseInfo": {"key": "mit", "name": "MIT License", "nickname": ""}, "visibility": "PUBLIC"})  # noqa: E731


def repo(tmp_path, readme="# x\nsee docs/screenshots/a.png docs/diagrams/a.svg\n", tags=(), extra=None):
    git = lambda *a: subprocess.run(["git", *a], cwd=tmp_path, check=True, capture_output=True)  # noqa: E731
    git("init", "-q")
    git("config", "user.email", "t@t.test")
    git("config", "user.name", "t")
    files = {"README.md": readme, "LICENSE": "MIT License\n\nCopyright", "postman/a.json": "{}", "docs/ARCHITECTURE.md": "```mermaid\nflowchart LR\n```\n",
             "docs/diagrams/a.svg": "<svg/>", **(extra or {})}
    for name, text in files.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    git("add", "-A")
    git("commit", "-qm", "init")
    for t in tags:
        git("tag", t)
    return tmp_path


def run(tmp_path, gh=OK_GH, today=dt.date(2026, 11, 3), **kw):
    return {n: (ok, note) for n, ok, note in cs.check(root=tmp_path, today=today, gh=gh, **kw)}


def test_clean_repo_with_expected_tags_passes(tmp_path):
    res = run(repo(tmp_path, tags=["m1-day1-checks", "m2-catalog-tasks"]))
    assert all(ok for ok, _ in res.values()), res


def test_any_placeholder_fails_in_readme_or_submission_docs(tmp_path):
    res = run(repo(tmp_path, readme="login <<JUDGE_BUYER_EMAIL>> docs/screenshots/ docs/diagrams/", extra={"docs/submission/a.md": "<<LIVE_URL>>"}, tags=["m1-day1-checks", "m2-catalog-tasks"]))
    ok, note = res["no <<PLACEHOLDER>> left in README.md / docs/submission"]
    assert not ok and "JUDGE_BUYER_EMAIL" in note and "LIVE_URL" in note


def test_missing_due_tag_fails_but_future_tags_are_not_required(tmp_path):
    res = run(repo(tmp_path, tags=["m1-day1-checks"]))
    assert res["tag m2-catalog-tasks exists (due 2026-11-02)"][0] is False
    assert not any(k.startswith("tag m4") for k in res)
    assert run(tmp_path, today=dt.date(2026, 11, 12))["tag m8-submission exists (due 2026-11-12)"][0] is False


def test_license_and_visibility_come_from_gh_and_failure_to_ask_fails_closed(tmp_path):
    r = repo(tmp_path, tags=["m1-day1-checks", "m2-catalog-tasks"])
    bad = lambda *a: json.dumps({"licenseInfo": None, "visibility": "PRIVATE"})  # noqa: E731
    res = run(r, gh=bad)
    assert not res["GitHub license is MIT"][0] and not res["GitHub repo is public"][0]
    def boom(*a): raise FileNotFoundError("gh")
    assert not run(r, gh=boom)["GitHub repo is public"][0]


def test_tracked_env_file_and_secret_shapes_and_bad_json_fail(tmp_path):
    r = repo(tmp_path, tags=["m1-day1-checks", "m2-catalog-tasks"], extra={".env": "A=1", "postman/bad.json": "{", "notes.txt": "hf_" + "a" * 30})
    res = run(r)
    assert not res["no .env tracked"][0] and not res["secret scan clean"][0] and not res["bad.json parses"][0]
