"""Manifest-backed real-snapshot task cases; contains no raw products or reviews."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from tasks.batch import BatchConfig
from tasks.engine import SplitConfig


MANIFESTS = Path(__file__).resolve().parents[2] / "data" / "manifests"


@dataclass(frozen=True)
class RealSnapshotTaskCase:
    category: str
    manifest_hash: str
    product_count: int
    review_count: int
    batch_config: BatchConfig
    review_sensitive: bool


def real_snapshot_cases() -> tuple[RealSnapshotTaskCase, ...]:
    cases = []
    for path in sorted(MANIFESTS.glob("*.json")):
        manifest = json.loads(path.read_text())
        cases.append(RealSnapshotTaskCase(
            category=manifest["category"], manifest_hash=manifest["sha256"],
            product_count=manifest["products"], review_count=manifest["reviews"],
            batch_config=BatchConfig(
                size=20, feasible_percent=75,
                split=SplitConfig(train=80, validation=10, test=10),
            ),
            review_sensitive=manifest["reviews"] > 0,
        ))
    return tuple(cases)
