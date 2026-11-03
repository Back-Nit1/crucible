"""Export every Mermaid block in docs/ARCHITECTURE.md to docs/diagrams/NN-<heading>.svg with a pinned mermaid-cli.
  uv run python -m scripts.export_diagrams [--chrome PATH]
Needs node/npx. mermaid-cli drives a headless Chromium: pass --chrome (or PUPPETEER_EXECUTABLE_PATH) if puppeteer has none downloaded."""
import argparse
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

CLI = "@mermaid-js/mermaid-cli@11.4.2"
ROOT = Path(__file__).resolve().parents[1]


def blocks(text: str):
    head, lines, n, i = "diagram", text.splitlines(), 0, 0
    while i < len(lines):
        if lines[i].startswith("## "):
            head = lines[i][3:]
        if lines[i].startswith("```mermaid"):
            j = i + 1
            while not lines[j].startswith("```"):
                j += 1
            n += 1
            yield f"{n:02d}-" + re.sub(r"[^a-z0-9]+", "-", re.sub(r"\(.*?\)", "", head).lower()).strip("-"), "\n".join(lines[i + 1:j]) + "\n"
            i = j
        i += 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chrome", default=os.environ.get("PUPPETEER_EXECUTABLE_PATH"))
    a = ap.parse_args(argv)
    out = ROOT / "docs" / "diagrams"
    out.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp, "pp.json")
        cfg.write_text(json.dumps({"args": ["--no-sandbox"], **({"executablePath": a.chrome} if a.chrome else {})}))
        for old in out.glob("*.svg"):
            old.unlink()
        for name, src in blocks((ROOT / "docs" / "ARCHITECTURE.md").read_text()):
            mmd = Path(tmp, f"{name}.mmd")
            mmd.write_text(src)
            subprocess.run(["npx", "-y", CLI, "-p", str(cfg), "-i", str(mmd), "-o", str(out / f"{name}.svg"), "-b", "transparent"], check=True)
            print("wrote", out / f"{name}.svg")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
