"""Every top-level package must be declared in the shared package configuration."""
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {"agents", "api", "catalog", "eval", "memory", "modal_app", "payments", "scoring", "tasks", "training", "world"}


def test_all_runtime_packages_are_declared_and_exist():
    cfg = tomllib.loads((ROOT / "pyproject.toml").read_text())
    include = {p.rstrip("*") for p in cfg["tool"]["setuptools"]["packages"]["find"]["include"]}
    assert EXPECTED <= include
    assert all((ROOT / p / "__init__.py").exists() for p in EXPECTED)


def test_packages_are_importable():
    import importlib
    for p in EXPECTED:
        importlib.import_module(p)
