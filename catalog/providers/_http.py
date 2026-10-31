"""Tiny stdlib JSON-over-HTTP helper shared by the Channel3 and Elastic clients."""
import json
import urllib.error
import urllib.request


class HttpError(RuntimeError):
    def __init__(self, status: int, body: str, url: str):
        super().__init__(f"HTTP {status} {url}: {body[:300]}")
        self.status, self.body, self.url = status, body, url


def request_json(method: str, url: str, headers: dict, body=None, timeout: float = 60):
    """Send `body` (dict -> JSON, str/bytes -> as is) and return the parsed JSON response."""
    if isinstance(body, dict):
        data = json.dumps(body).encode()
    elif isinstance(body, str):
        data = body.encode()
    else:
        data = body
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        raise HttpError(e.code, e.read().decode(errors="replace"), url) from None
    return json.loads(raw) if raw else {}
