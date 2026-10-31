"""Amazon Reviews 2023 (McAuley Lab; Hou et al. 2024, arXiv:2403.03952) streaming reader.
Field names verified against live records 2026-10-30. Files are multi-GB, so we range-read."""
import json
import urllib.request
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path

BASE = "https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023/resolve/main/raw"


def meta_url(category: str) -> str:
    return f"{BASE}/meta_categories/meta_{category}.jsonl"


def review_url(category: str) -> str:
    return f"{BASE}/review_categories/{category}.jsonl"


def iter_jsonl(url: str, max_bytes: int, offset: int = 0, cache_dir: str | None = None):
    """Yield records from `max_bytes` of a remote JSONL starting at byte `offset`.
    Partial first (offset>0) and last lines are dropped. `cache_dir` keeps the raw window on disk."""
    path = Path(cache_dir) / f"{url.rsplit('/', 1)[1]}@{offset}+{max_bytes}" if cache_dir else None
    if path and path.exists():
        data = path.read_bytes()
    else:
        req = urllib.request.Request(url, headers={"Range": f"bytes={offset}-{offset + max_bytes - 1}"})
        with urllib.request.urlopen(req, timeout=300) as r:
            data = r.read()
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
    lines = data.split(b"\n")[:-1]
    for line in lines[1:] if offset else lines:
        yield json.loads(line)


def parse_price(raw) -> Decimal | None:
    """Prices are numbers or null in the data; anything else is treated as absent."""
    try:
        p = Decimal(str(raw))
    except (InvalidOperation, TypeError):
        return None
    return p if p > 0 else None


def coverage(metas, min_reviews: int = 5) -> dict:
    """Day-1 check 4b/8: how many products are usable for tasks."""
    c = Counter()
    for m in metas:
        c["products"] += 1
        has_price = parse_price(m.get("price")) is not None
        many = (m.get("rating_number") or 0) >= min_reviews
        c["price"] += has_price
        c["reviews>=min"] += many
        c["usable"] += has_price and many
        c["features"] += bool(m.get("features"))
    return dict(c)
