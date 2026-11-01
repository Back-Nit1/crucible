"""scripts/paypal_live_check.py: gating, exit codes, and the full flow against a stateful fake of Orders v2."""
import json

import httpx
import pytest

from payments.kernel_approver import ApprovalBlocked, KernelError
from scripts import paypal_live_check as lc
from tests.test_payments_contract import SECRET, _sandbox

ENV = ("PAYPAL_CLIENT_ID=cid\nPAYPAL_CLIENT_SECRET=topsecretvalue\nPAYPAL_ENV=sandbox\nKERNEL_API_KEY=k\n"
       "PAYPAL_SANDBOX_BUYER_EMAIL=buyer@x.test\nPAYPAL_SANDBOX_BUYER_PASSWORD=buyerpw\n")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in lc.NEEDED + ["CRUCIBLE_KERNEL_BUYER_APPROVAL_AUTHORIZED"]:
        monkeypatch.delenv(k, raising=False)


def run(tmp_path, capsys, env=ENV, args=("--confirm-sandbox-run",), rig=None, approve="rig", out=True):
    f = tmp_path / ".env"
    f.write_text(env)
    rig = rig or _sandbox()
    appr = (lambda oid: rig.approve(oid)) if approve == "rig" else approve
    code = lc.main(["--env-file", str(f), *args], backend=rig.backend, approve=appr, out=tmp_path / "out.json" if out else None)
    return code, capsys.readouterr().out, rig


def authorize(monkeypatch):
    monkeypatch.setenv("CRUCIBLE_KERNEL_BUYER_APPROVAL_AUTHORIZED", "1")


def test_missing_buyer_credentials_exit_3_with_names_only(tmp_path, capsys):
    code, out, rig = run(tmp_path, capsys, env=ENV.split("PAYPAL_SANDBOX_BUYER_EMAIL")[0])
    assert code == lc.CONFIG == 3
    d = json.loads(out)
    assert d["missing_env_names"] == ["PAYPAL_SANDBOX_BUYER_EMAIL", "PAYPAL_SANDBOX_BUYER_PASSWORD"] and "topsecretvalue" not in out
    assert rig.fake.calls == []


@pytest.mark.parametrize("env_value", ["live", "", "Sandbox"])
def test_environment_must_be_exactly_sandbox_by_name_only(tmp_path, capsys, env_value):
    code, out, rig = run(tmp_path, capsys, env=ENV.replace("PAYPAL_ENV=sandbox", f"PAYPAL_ENV={env_value}"))
    assert code == 3 and "PAYPAL_ENV(must be exactly 'sandbox')" in json.loads(out)["missing_env_names"]
    assert rig.fake.calls == [] and (env_value != "live" or "live" not in out.replace("PAYPAL_ENV", ""))


def test_without_explicit_confirmation_nothing_runs(tmp_path, capsys, monkeypatch):
    authorize(monkeypatch)
    code, out, rig = run(tmp_path, capsys, args=())
    assert code == lc.AUTH == 4 and json.loads(out)["required"] == ["--confirm-sandbox-run"] and rig.fake.calls == []


def test_without_kernel_authorization_nothing_runs(tmp_path, capsys):
    code, out, rig = run(tmp_path, capsys)
    assert code == 4 and json.loads(out)["required"] == ["CRUCIBLE_KERNEL_BUYER_APPROVAL_AUTHORIZED=1"] and rig.fake.calls == []


def test_full_flow_passes_with_latency_ledger_and_clean_evidence(tmp_path, capsys, monkeypatch):
    authorize(monkeypatch)
    code, out, rig = run(tmp_path, capsys)
    d = json.loads(out)
    assert code == 0 and d["status"] == "passed" and d["amount"] == "1.00" and d["currency"] == "USD" and d["environment"] == "sandbox"
    assert [s["step"] for s in d["steps"]] == ["oauth", "create_order", "create_replay", "get_order", "kernel_approval", "get_order_after_approval",
                                               "capture", "capture_record", "capture_replay", "duplicate_capture"]
    assert all(s["ok"] and isinstance(s["ms"], int) for s in d["steps"])
    assert (d["captures_on_order"], d["duplicate_capture_result"], d["replay_same_capture_id"]) == (1, "ORDER_ALREADY_CAPTURED", True)
    assert [e["event"] for e in d["ledger"]] == ["proposal", "approval", "confirmation", "capture", "capture"]
    assert [e.get("idempotency_outcome") for e in d["ledger"] if e["event"] == "capture"] == ["created", "replayed"]
    assert len(rig.fake.orders["ORD1"]["purchase_units"][0]["payments"]["captures"]) == 1
    evidence = (tmp_path / "out.json").read_text()
    for banned in ("topsecretvalue", "buyerpw", "buyer@x.test", "https://", SECRET, "Bearer", "dbg", "capture-ORD1"):
        assert banned not in evidence and banned not in out


def test_no_kernel_stops_at_the_approval_url_without_capture(tmp_path, capsys):
    f = ENV.split("KERNEL_API_KEY")[0]
    code, out, rig = run(tmp_path, capsys, env=f, args=("--confirm-sandbox-run", "--no-kernel"), approve=None)
    d = json.loads(out)
    assert code == lc.BLOCKED == 5 and d["status"] == "approval_required" and d["approval_url_allowlisted"] is True
    assert not any(p.endswith("/capture") for _, p, _ in rig.fake.calls)


def test_challenge_is_exit_5_kernel_failure_7_paypal_failure_6_assertion_8(tmp_path, capsys, monkeypatch):
    authorize(monkeypatch)

    def blocked(oid):
        raise ApprovalBlocked("challenge detected at after_login")

    def broken(oid):
        raise KernelError("browser create failed: ConnectionError")

    code, out, rig = run(tmp_path, capsys, approve=blocked)
    assert code == 5 and json.loads(out)["status"] == "approval_blocked" and not any(p.endswith("/capture") for _, p, _ in rig.fake.calls)
    assert run(tmp_path, capsys, approve=broken)[0] == 7
    rig = _sandbox()
    rig.fake.faults = [httpx.Response(400, json={"name": "INVALID_REQUEST", "message": "LEAK", "details": [{"issue": "MALFORMED_REQUEST_JSON"}]})]
    code, out, _ = run(tmp_path, capsys, rig=rig)
    assert code == 6 and "MALFORMED_REQUEST_JSON" in out and "LEAK" not in out
    code, out, _ = run(tmp_path, capsys, approve=lambda oid: None)  # "approved" but PayPal says otherwise
    assert code == 8 and json.loads(out)["status"] == "assertion_failed"


def test_duplicate_charge_is_caught_if_paypal_ever_accepted_a_second_capture(tmp_path, capsys, monkeypatch):
    authorize(monkeypatch)
    rig = _sandbox()
    rig.backend.duplicate_capture_code = lambda oid: "CAPTURED_AGAIN"
    code, out, _ = run(tmp_path, capsys, rig=rig)
    assert code == 8 and "duplicate capture not rejected" in out
