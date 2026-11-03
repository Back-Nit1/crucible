"""scripts/verify_deploy.py against fake web + API hosts (no network)."""
import httpx

from scripts import verify_deploy as vd

WEB, API = "https://web.test", "https://api.test"


def site(*, cors=True, model_503=True, leak="", generations=True, model_configured=False):
    def handler(req: httpx.Request) -> httpx.Response:
        host, path = req.url.host, req.url.path
        if host == "api.test":
            if path == "/health": return httpx.Response(200, json={"status": "ok"})
            if path == "/ready": return httpx.Response(200, json={"status": "ok", "checks": {"model_configured": model_configured}})
            if path == "/config": return httpx.Response(200, json={"payments": "sandbox", "demo_mode": True, "catalog": "elastic_snapshot"})
            if path == "/world/generations": return httpx.Response(200, json={"items": [{"generation_id": "g1"}] if generations else []})
            if path == "/world/generations/g1": return httpx.Response(200, json={})
            if path == "/world/episodes": return httpx.Response(200, json={"items": [{"episode_id": "e/1"}]})
            if path == "/world/episodes/e/1": return httpx.Response(200, json={})
            if path == "/purchase/confirm" and req.method == "OPTIONS":
                origin = req.headers["origin"]
                return httpx.Response(200, headers={"access-control-allow-origin": origin} if cors and origin == WEB else {})
            if path == "/agent/runs":
                return httpx.Response(503 if model_503 else 200, json={"error": {"code": "model_unavailable"}})
        if host == "web.test":
            if path == "/": return httpx.Response(200, text='<script src="/_next/static/a.js"></script>')
            if path.startswith("/_next/static"): return httpx.Response(200, text="var x=1;" + leak)
            return httpx.Response(200, text="ok")
        return httpx.Response(404)
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def run(capsys, **kw):
    code = vd.main([WEB, API], client=site(**kw))
    return code, capsys.readouterr().out


def test_healthy_deployment_passes_every_check(capsys):
    code, out = run(capsys)
    assert code == 0 and "FAIL" not in out and "11/11 checks passed" in out


def test_missing_cors_origin_fails(capsys):
    code, out = run(capsys, cors=False)
    assert code == 1 and "FAIL CORS preflight" in out


def test_model_path_must_be_typed_503_unless_a_model_is_configured(capsys):
    assert run(capsys, model_503=False)[0] == 1
    code, out = run(capsys, model_503=False, model_configured=True)  # configured: never POST, so no spend
    assert code == 0 and "skipped" in out


def test_secret_in_web_bundle_fails_without_printing_it(capsys):
    code, out = run(capsys, leak=" ELASTIC_API_KEY ")
    assert code == 1 and "FAIL no secret patterns" in out
    code, out = run(capsys, leak="hf_" + "a" * 30)
    assert code == 1 and "a" * 30 not in out


def test_empty_trace_store_fails_the_generation_check(capsys):
    code, out = run(capsys, generations=False)
    assert code == 1 and "FAIL generation detail" in out


def test_unreachable_host_fails_cleanly(capsys):
    def boom(req): raise httpx.ConnectError("down")
    code = vd.main([WEB, API], client=httpx.Client(transport=httpx.MockTransport(boom)))
    assert code == 1 and "PASS" not in capsys.readouterr().out
