"""Tiny stdlib JSON-over-HTTP helper shared by the Channel3 and Elastic clients."""
import json
import time
import urllib.error
import urllib.request
from decimal import Decimal


RETRIES, RETRY_STATUS = 3, {429, 502, 503, 504}  # every caller sends idempotent requests (reads, keyed bulk writes)


class HttpError(RuntimeError):
    def __init__(self, status: int, body: str, url: str):
        super().__init__(f"HTTP {status} {url}: {body[:300]}")
        self.status, self.body, self.url = status, body, url


def _num(o):
    if isinstance(o, Decimal):  # price filters arrive as Decimal; the wire format is a JSON number
        return float(o)
    raise TypeError(f"{type(o).__name__} is not JSON serializable")


def request_json(method: str, url: str, headers: dict, body=None, timeout: float = 60):
    """Send `body` (dict -> JSON, str/bytes -> as is) and return the parsed JSON response."""
    if isinstance(body, dict):
        data = json.dumps(body, default=_num).encode()
    elif isinstance(body, str):
        data = body.encode()
    else:
        data = body
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    for attempt in range(RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
            break
        except urllib.error.HTTPError as e:
            if e.code in RETRY_STATUS and attempt < RETRIES:  # rate limit / gateway hiccup under many parallel episodes
                time.sleep(2 ** attempt)
                continue
            raise HttpError(e.code, e.read().decode(errors="replace"), url) from None
    return json.loads(raw) if raw else {}
