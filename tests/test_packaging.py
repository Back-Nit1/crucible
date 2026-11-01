"""Every shipped package is declared in pyproject and every module imports (no import-time network, GPU or env needs)."""
import importlib
import pkgutil
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP = {"modal_app.day1_probe", "modal_app.world_runner", "modal_app.qwen_inference"}  # build Modal images at import: deploy-only


def test_every_package_dir_is_declared_for_packaging():
    declared = set(tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["setuptools"]["packages"])
    on_disk = {p.parent.relative_to(ROOT).as_posix().replace("/", ".") for p in ROOT.glob("*/__init__.py")
               if p.parent.name not in {"tests", "scripts", ".venv"} and not p.parent.name.startswith(".")}
    on_disk |= {p.parent.relative_to(ROOT).as_posix().replace("/", ".") for p in ROOT.glob("*/*/__init__.py")
                if p.parent.parent.name in on_disk}
    assert on_disk <= declared, sorted(on_disk - declared)


def test_every_module_imports_cleanly():
    failures = []
    for pkg in sorted(set(tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["setuptools"]["packages"])):
        module = importlib.import_module(pkg)
        for info in pkgutil.iter_modules(module.__path__, pkg + "."):
            if info.name in SKIP:
                continue
            try:
                importlib.import_module(info.name)
            except Exception as exc:  # report every broken module at once
                failures.append(f"{info.name}: {type(exc).__name__}")
    assert not failures, failures
