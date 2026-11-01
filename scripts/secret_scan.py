"""Fail if any secret VALUE from an env file (or a credential-shaped string) appears in a git-tracked file.
  uv run python -m scripts.secret_scan --env-file <.env>
Prints file names and rule names only, never the matched text."""
import argparse
import re
import subprocess
import sys
from pathlib import Path

SHAPES = {"modal_token": r"\b(?:ak|as)-[A-Za-z0-9_-]{16,}\b", "hf_token": r"\bhf_[A-Za-z0-9]{20,}\b",
          "private_key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "bearer": r"(?i)authorization:\s*bearer\s+[A-Za-z0-9._-]{20,}",
          "elastic_apikey_header": r"ApiKey\s+[A-Za-z0-9+/=]{30,}"}
BENIGN = {"true", "false", "sandbox", "mock", "live", "1", "0"}


def env_values(path: str) -> set[str]:
    out = set()
    for line in Path(path).read_text().splitlines():
        k, _, v = line.partition("=")
        v = v.strip().strip("\"'")
        if k.strip() and not k.lstrip().startswith("#") and len(v) >= 8 and v.lower() not in BENIGN:
            out.add(v)
    return out


def scan(files: list[Path], values: set[str]) -> list[tuple[str, str]]:
    hits = []
    for f in files:
        try:
            text = f.read_text(errors="ignore")
        except OSError:
            continue
        hits += [(str(f), "env_value") for v in values if v in text]
        hits += [(str(f), name) for name, rx in SHAPES.items() if re.search(rx, text)]
    return hits


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file")
    a = ap.parse_args(argv)
    tracked = [Path(p) for p in subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True).stdout.splitlines()
               if not p.startswith("docs/graph/")]
    hits = scan(tracked, env_values(a.env_file) if a.env_file else set())
    for path, rule in sorted(set(hits)):
        print(f"{rule}: {path}")
    print(f"scanned {len(tracked)} tracked files, {len(set(hits))} finding(s)")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
