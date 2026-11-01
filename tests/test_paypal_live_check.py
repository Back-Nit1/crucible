import json

from scripts import paypal_live_check


def test_blocks_with_names_only_when_buyer_credentials_are_missing(tmp_path, capsys, monkeypatch):
    for k in paypal_live_check.NEEDED:
        monkeypatch.delenv(k, raising=False)
    env = tmp_path / ".env"
    env.write_text("PAYPAL_CLIENT_ID=abc\nPAYPAL_CLIENT_SECRET=topsecretvalue\nPAYPAL_ENV=sandbox\nKERNEL_API_KEY=k\n")
    assert paypal_live_check.main(["--env-file", str(env)]) == 3
    out = capsys.readouterr().out
    assert json.loads(out)["missing_env_names"] == ["PAYPAL_SANDBOX_BUYER_EMAIL", "PAYPAL_SANDBOX_BUYER_PASSWORD"]
    assert "topsecretvalue" not in out


def test_refuses_a_non_sandbox_environment_by_name_only(tmp_path, capsys, monkeypatch):
    for k in paypal_live_check.NEEDED:
        monkeypatch.delenv(k, raising=False)
    env = tmp_path / ".env"
    env.write_text("PAYPAL_CLIENT_ID=a\nPAYPAL_CLIENT_SECRET=b\nPAYPAL_ENV=live\nKERNEL_API_KEY=k\n"
                   "PAYPAL_SANDBOX_BUYER_EMAIL=e\nPAYPAL_SANDBOX_BUYER_PASSWORD=p\n")
    assert paypal_live_check.main(["--env-file", str(env)]) == 3
    out = capsys.readouterr().out
    assert "PAYPAL_ENV(must be 'sandbox')" in json.loads(out)["missing_env_names"] and "live" not in out.replace("sandbox", "")


def test_the_sandbox_backend_refuses_live_and_pins_the_sandbox_host(monkeypatch):
    import pytest
    from payments.sandbox import SANDBOX_URL, SandboxPayments
    assert SANDBOX_URL == "https://api-m.sandbox.paypal.com"
    monkeypatch.setenv("PAYPAL_ENV", "live")
    with pytest.raises(RuntimeError):
        SandboxPayments("id", "secret")
