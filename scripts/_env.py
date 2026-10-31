"""Load named keys from an env file into os.environ without printing them."""
import os
from pathlib import Path


def load(path: str, keys: set[str]) -> None:
    for line in Path(path).read_text().splitlines():
        k, _, v = line.partition("=")
        if k.strip() in keys and v.strip():
            os.environ[k.strip()] = v.strip().strip("\"'")
