import json

from scripts import paypal_live_check


def test_blocks_with_names_only_when_buyer_credentials_are_missing(tmp_path, capsys, monkeypatch):
    for k in paypal_live_check.NEEDED:
        monkeypatch.delenv(k, raising=False)
    env = tmp_path / ".env"
    env.write_text("PAYPAL_CLIENT_ID=abc\nPAYPAL_CLIENT_SECRET=topsecretvalue\nKERNEL_API_KEY=k\n")
    assert paypal_live_check.main(["--env-file", str(env)]) == 3
    out = capsys.readouterr().out
    assert json.loads(out)["missing_env_names"] == ["PAYPAL_SANDBOX_BUYER_EMAIL", "PAYPAL_SANDBOX_BUYER_PASSWORD"]
    assert "topsecretvalue" not in out
