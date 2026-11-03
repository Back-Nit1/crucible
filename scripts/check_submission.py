"""Pre-submission gate. Exit 0 only when nothing the user still owns (judge credentials, live URL) is left as a `<<PLACEHOLDER>>`
and the repo-level requirements hold.
  uv run python -m scripts.check_submission [--env-file <.env>] [--repo Back-Nit1/crucible] [--today YYYY-MM-DD]
Checks: no `<<...>>` in README.md / docs/submission/; MIT license visible on GitHub and repo public (`gh repo view`);
milestone tags m1..m8 exist once their date has passed; secret scan clean; Postman JSON parses; no .env tracked;
every Mermaid diagram has an SVG and the README references the screenshots."""
import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

from scripts.secret_scan import env_values, scan

ROOT = Path(__file__).resolve().parents[1]
PLACEHOLDER = re.compile(r"<<[A-Za-z0-9_ ]+>>")
# milestone tag -> first day it must exist (prompt.md section 16, Oct 30 start; m4..m8 as scheduled)
TAGS = {"m1-day1-checks": "2026-10-31", "m2-catalog-tasks": "2026-11-02", "m3-episode": "2026-11-04", "m4-world": "2026-11-06",
        "m5-train-eval": "2026-11-08", "m6-product": "2026-11-10", "m7-polish": "2026-11-11", "m8-submission": "2026-11-12"}


def sh(*cmd, root: Path = ROOT) -> str:
    return subprocess.run(cmd, cwd=root, capture_output=True, text=True, check=True).stdout


def placeholders(root: Path) -> list[str]:
    files = [root / "README.md", *sorted((root / "docs" / "submission").glob("**/*.md"))]
    return [f"{f.relative_to(root)}: {m}" for f in files if f.exists() for m in sorted(set(PLACEHOLDER.findall(f.read_text())))]


def check(root: Path = ROOT, repo: str | None = None, env_file: str | None = None, today: dt.date | None = None, gh=None) -> list[tuple[str, bool, str]]:
    today, res = today or dt.date.today(), []

    def add(name, ok, note=""):
        res.append((name, bool(ok), note))

    ph = placeholders(root)
    add("no <<PLACEHOLDER>> left in README.md / docs/submission", not ph, "; ".join(ph[:6]) + (f" (+{len(ph) - 6} more)" if len(ph) > 6 else ""))

    try:
        info = json.loads((gh or (lambda *a: sh("gh", *a, root=root)))("repo", "view", *([repo] if repo else []), "--json", "licenseInfo,visibility,url"))
        add("GitHub license is MIT", (info.get("licenseInfo") or {}).get("spdxId") == "MIT", str((info.get("licenseInfo") or {}).get("spdxId")))
        add("GitHub repo is public", info.get("visibility") == "PUBLIC", str(info.get("visibility")))
    except Exception as e:  # gh missing, not logged in, offline: unverified counts as failed
        add("GitHub license is MIT", False, f"gh repo view failed: {type(e).__name__}")
        add("GitHub repo is public", False, f"gh repo view failed: {type(e).__name__}")
    lic = root / "LICENSE"
    add("LICENSE file is MIT text", lic.exists() and "MIT License" in lic.read_text()[:200])

    tags = set(sh("git", "tag", root=root).split())
    for tag, due in TAGS.items():
        if today >= dt.date.fromisoformat(due):
            add(f"tag {tag} exists (due {due})", tag in tags)

    tracked = sh("git", "ls-files", root=root).splitlines()
    add("no .env tracked", not [f for f in tracked if re.search(r"(^|/)\.env(\.|$)", f) and not f.endswith(".example")], "")
    hits = scan([root / f for f in tracked if not f.startswith("docs/graph/")], env_values(env_file) if env_file else set())
    add("secret scan clean", not hits, f"{len({h for h in hits})} finding(s)" if hits else ("with env values" if env_file else "shapes only (no --env-file)"))

    for f in sorted((root / "postman").glob("*.json")):
        try:
            json.loads(f.read_text())
            add(f"{f.name} parses", True)
        except ValueError as e:
            add(f"{f.name} parses", False, str(e)[:80])

    arch = (root / "docs" / "ARCHITECTURE.md").read_text()
    n, svgs = arch.count("```mermaid"), list((root / "docs" / "diagrams").glob("*.svg"))
    add("every Mermaid diagram has an SVG in docs/diagrams", len(svgs) >= n, f"{len(svgs)} svg / {n} diagrams")
    readme = (root / "README.md").read_text()
    add("README references docs/screenshots and docs/diagrams", "docs/screenshots/" in readme and "docs/diagrams/" in readme)
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file")
    ap.add_argument("--repo")
    ap.add_argument("--today", type=dt.date.fromisoformat)
    a = ap.parse_args(argv)
    res = check(repo=a.repo, env_file=a.env_file, today=a.today)
    for name, ok, note in res:
        print(f"{'PASS' if ok else 'FAIL'} {name}" + (f": {note}" if note else ""))
    failed = [n for n, ok, _ in res if not ok]
    print(f"{len(res) - len(failed)}/{len(res)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
