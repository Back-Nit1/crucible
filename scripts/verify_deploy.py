"""Smoke-check a deployed Crucible (web + API). Read-only: GETs, one CORS preflight, and one POST only when the model is NOT configured.
  uv run python -m scripts.verify_deploy <web_url> <api_url>
Exit 0 = every check passed, 1 = at least one failed. Prints check names and short reasons, never response bodies or secrets."""
import argparse
import re
import sys
from urllib.parse import urljoin

import httpx

from scripts.secret_scan import SHAPES

BUNDLE_SECRETS = {**SHAPES, "paypal_secret_name": r"PAYPAL_CLIENT_SECRET|KERNEL_API_KEY|ELASTIC_API_KEY|MODAL_TOKEN_SECRET|CHANNEL3_API_KEY"}
MAX_SCRIPTS = 40


def check(name, fn, results):
    try:
        note = fn()
        results.append((name, True, note or ""))
    except Exception as e:  # a failed check is a result, not a crash
        results.append((name, False, f"{type(e).__name__}: {str(e)[:160]}"))


def ok(r, what):
    assert r.status_code == 200, f"{what} -> HTTP {r.status_code}"
    return r


def verify(web: str, api: str, client: httpx.Client) -> list[tuple[str, bool, str]]:
    web, api, res = web.rstrip("/"), api.rstrip("/"), []
    g = lambda base, path, **kw: client.get(base + path, **kw)  # noqa: E731
    state: dict = {}

    def health():
        assert ok(g(api, "/health"), "/health").json()["status"] == "ok"
    check("api /health", health, res)

    def ready():
        j = ok(g(api, "/ready"), "/ready").json()
        state["model_configured"] = j["checks"]["model_configured"]
        return ", ".join(f"{k}={v}" for k, v in j["checks"].items())
    check("api /ready", ready, res)

    def config():
        j = ok(g(api, "/config"), "/config").json()
        return f"payments={j['payments']} demo_mode={j['demo_mode']} catalog={j['catalog']}"
    check("api /config", config, res)

    for path in ("/", "/system", "/world"):
        check(f"web {path}", lambda p=path: ok(g(web, p), p) and None, res)

    def gen():
        items = ok(g(api, "/world/generations", params={"limit": 1}), "/world/generations").json()["items"]
        assert items, "no generations in the trace store"
        gid = items[0]["generation_id"]
        ok(g(api, f"/world/generations/{gid}"), "generation detail")
        ok(g(web, f"/world/generations/{gid}"), "web generation page")
        return gid
    check("generation detail (api + web)", gen, res)

    def episode():
        items = ok(g(api, "/world/episodes", params={"limit": 1}), "/world/episodes").json()["items"]
        assert items, "no episodes in the trace store"
        eid = items[0]["episode_id"]
        ok(g(api, f"/world/episodes/{eid}"), "episode detail")
        ok(g(web, f"/episodes/{eid}"), "web episode page")
        return eid
    check("episode detail (api + web)", episode, res)

    def cors():
        h = {"Origin": web, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"}
        r = client.options(api + "/purchase/confirm", headers=h)
        assert r.headers.get("access-control-allow-origin") == web, "web origin not allowed (set CORS_ALLOW_ORIGINS on the API)"
        evil = client.options(api + "/purchase/confirm", headers=h | {"Origin": "https://evil.invalid"})
        assert "access-control-allow-origin" not in evil.headers, "API allows an arbitrary origin"
    check("CORS preflight from web origin", cors, res)

    def model():
        if state.get("model_configured"):
            return "skipped: a model is configured and calling it would spend compute"
        r = client.post(api + "/agent/runs", json={"message": "verify_deploy probe"})
        assert r.status_code == 503 and r.json()["error"]["code"] == "model_unavailable", f"expected typed 503 model_unavailable, got {r.status_code}"
    check("typed model_unavailable", model, res)

    def bundle():
        page = ok(g(web, "/"), "/").text
        srcs = list(dict.fromkeys(re.findall(r'(?:src|href)="([^"]+\.js[^"]*)"', page)))[:MAX_SCRIPTS]
        assert srcs, "no script bundles found on /"
        hits = []
        for s in srcs:
            text = client.get(urljoin(web + "/", s)).text
            hits += [f"{n}@{s.rsplit('/', 1)[-1]}" for n, rx in BUNDLE_SECRETS.items() if re.search(rx, text)]
        assert not hits, "secret-shaped strings in web bundle: " + ", ".join(sorted(set(hits)))
        return f"{len(srcs)} scripts scanned"
    check("no secret patterns in web bundle", bundle, res)
    return res


def main(argv=None, client: httpx.Client | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("web_url")
    ap.add_argument("api_url")
    a = ap.parse_args(argv)
    with client or httpx.Client(timeout=60, follow_redirects=True) as c:  # free Render cold starts take ~60 s
        results = verify(a.web_url, a.api_url, c)
    for name, passed, note in results:
        print(f"{'PASS' if passed else 'FAIL'} {name}" + (f": {note}" if note else ""))
    failed = [n for n, p, _ in results if not p]
    print(f"{len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
