"""Explicit report writers used by CLI/runtime layers."""

from pathlib import Path

from eval.comparison import ComparisonReport
from eval.harness import EvaluationReport


def write_evaluation(report: EvaluationReport, output_dir: str | Path, stem: str) -> tuple[Path, Path]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    json_path = root / f"{stem}.json"
    markdown_path = root / f"{stem}.md"
    json_path.write_text(report.to_json() + "\n")
    markdown_path.write_text(report.to_markdown())
    return json_path, markdown_path


def write_comparison(report: ComparisonReport, output_dir: str | Path, stem: str) -> tuple[Path, Path]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    json_path = root / f"{stem}.json"
    markdown_path = root / f"{stem}.md"
    json_path.write_text(report.to_json() + "\n")
    markdown_path.write_text(report.to_markdown())
    return json_path, markdown_path
