import io
import urllib.error

import pytest

from catalog.providers import _http


def _err(code):
    return urllib.error.HTTPError("http://x", code, "m", {}, io.BytesIO(b"busy"))


class _Resp:
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def read(self): return b'{"ok": 1}'


def test_a_rate_limit_is_retried_then_succeeds_and_other_errors_are_not(monkeypatch):
    monkeypatch.setattr(_http.time, "sleep", lambda s: None)
    calls = iter([_err(429), _err(503), _Resp()])

    def fake(req, timeout):
        r = next(calls)
        if isinstance(r, Exception):
            raise r
        return r
    monkeypatch.setattr(_http.urllib.request, "urlopen", fake)
    assert _http.request_json("GET", "http://x", {}) == {"ok": 1}
    monkeypatch.setattr(_http.urllib.request, "urlopen", lambda req, timeout: (_ for _ in ()).throw(_err(400)))
    with pytest.raises(_http.HttpError):
        _http.request_json("GET", "http://x", {})
