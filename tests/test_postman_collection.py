"""Postman collection/environment: complete sandbox flow, no secrets, no live hosts, scripts parse."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent / "postman"
COL = json.loads((ROOT / "crucible.postman_collection.json").read_text())
ENV = json.loads((ROOT / "crucible.postman_environment.json").read_text())


def walk(items, path=""):
    for i in items:
        if "item" in i:
            yield from walk(i["item"], f"{path}{i['name']}/")
        else:
            yield f"{path}{i['name']}", i


REQS = dict(walk(COL["item"]))


def test_environment_is_blank_placeholders_with_the_sandbox_host():
    vals = {v["key"]: v for v in ENV["values"]}
    assert vals["paypal_base_url"]["value"] == "https://api-m.sandbox.paypal.com"
    for key, v in vals.items():
        if key not in {"paypal_base_url", "api_base_url", "budget_cap", "generation_id"}:
            assert v["value"] == "", key
    for key in ("PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "paypal_access_token", "paypal_approval_url"):
        assert vals[key]["type"] == "secret"


def test_no_live_hosts_and_no_embedded_credentials():
    blob = (ROOT / "crucible.postman_collection.json").read_text() + (ROOT / "crucible.postman_environment.json").read_text()
    assert not re.search(r"api-m\.paypal\.com|www\.paypal\.com|api\.paypal\.com", blob)
    assert not re.search(r"eyJ[A-Za-z0-9_-]{10,}|A[A-Za-z0-9_-]{60,}|Bearer [A-Za-z0-9]{20,}", blob)
    for name, r in REQS.items():
        if name.startswith("PayPal Sandbox/"):
            assert r["request"]["url"]["raw"].startswith("{{paypal_base_url}}/"), name


def test_paypal_folder_covers_the_whole_flow_in_order():
    names = [n.split("/", 1)[1] for n in REQS if n.startswith("PayPal Sandbox/")]
    assert [re.match(r"(\d+)\.", n).group(1) for n in names] == [str(i) for i in range(1, 11)]
    joined = " | ".join(names).lower()
    for must in ("oauth", "create order", "replay", "get order", "before approval", "approval-state", "capture order", "duplicate", "exactly one"):
        assert must in joined, must


def test_capture_requests_cannot_hit_a_real_order_before_approval():
    pre = lambda n: "".join(next(e for e in REQS[n]["event"] if e["listen"] == "prerequest")["script"]["exec"])
    cap = next(n for n in REQS if "7. Capture order" in n)
    assert "=== 'APPROVED'" in pre(cap) and "RUN-STEP-6-FIRST" in pre(cap)
    early = next(n for n in REQS if "BEFORE approval" in n and "PayPal" in n)
    assert "NOT-AN-ORDER" in pre(early)
    confirm = next(n for n in REQS if "Confirm BEFORE PayPal approval" in n)
    assert "not-the-pending-order" in pre(confirm)


def test_buyer_folder_has_start_poll_confirm_and_failure_examples():
    names = [n for n in REQS if n.startswith("Crucible API/Buyer checkout")]
    text = " ".join(names)
    for must in ("Start run", "Poll", "user_confirmed=false", "BEFORE PayPal approval", "Confirm again (idempotent", "unknown pending"):
        assert must in text, must
    explicit = next(REQS[n] for n in names if "Confirm (explicit" in n)
    assert '"user_confirmed": true' in explicit["request"]["body"]["raw"]


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_every_script_parses():
    for name, r in REQS.items():
        for e in r.get("event", []):
            code = "\n".join(e["script"]["exec"])
            p = subprocess.run(["node", "-e", "new Function('pm', process.argv[1])", code], capture_output=True, text=True)
            assert p.returncode == 0, f"{name}: {p.stderr[:200]}"


def test_every_request_url_has_host_and_path_so_newman_can_run_it():
    for name, r in REQS.items():
        u = r["request"]["url"]
        assert u["host"] and isinstance(u["path"], list) and "".join(u["host"]) in u["raw"], name
