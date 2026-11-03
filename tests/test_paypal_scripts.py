"""The other PayPal scripts refuse to touch the network without configuration and explicit confirmation."""
import subprocess
import sys

import pytest

ENV = "PAYPAL_CLIENT_ID=cid\nPAYPAL_CLIENT_SECRET=topsecretvalue\nPAYPAL_ENV=sandbox\nKERNEL_API_KEY=k\n" \
      "PAYPAL_SANDBOX_BUYER_EMAIL=b@x.test\nPAYPAL_SANDBOX_BUYER_PASSWORD=buyerpw\n"


def run(script, env_text, tmp_path, *args):
    f = tmp_path / ".env"
    f.write_text(env_text)
    clean = {"PATH": "/usr/bin:/bin", "PYTHONPATH": "."}
    p = subprocess.run([sys.executable, f"scripts/{script}.py", "--env-file", str(f), *args], env=clean,
                       capture_output=True, text=True, timeout=30)
    return p.returncode, p.stdout + p.stderr


@pytest.mark.parametrize("script", ["paypal_latency", "paypal_kernel_e2e"])
def test_refuses_without_confirmation_and_without_sandbox(script, tmp_path):
    code, out = run(script, ENV.replace("sandbox", "live"), tmp_path, "--confirm-sandbox-run")
    assert code == 3 and "PAYPAL_ENV(must be exactly 'sandbox')" in out and "topsecretvalue" not in out
    code, out = run(script, ENV, tmp_path)
    assert code == 4 and "--confirm-sandbox-run" in out and "topsecretvalue" not in out


def test_kernel_e2e_also_needs_the_browser_authorization(tmp_path):
    code, out = run("paypal_kernel_e2e", ENV, tmp_path, "--confirm-sandbox-run")
    assert code == 4 and "CRUCIBLE_KERNEL_BUYER_APPROVAL_AUTHORIZED=1" in out


def test_live_tests_skip_without_credentials_or_outside_sandbox():
    from tests.test_payments_live import live_ready
    assert live_ready({"PAYPAL_CLIENT_ID": "a", "PAYPAL_CLIENT_SECRET": "b", "PAYPAL_ENV": "sandbox"})
    assert not live_ready({}) and not live_ready({"PAYPAL_CLIENT_ID": "a", "PAYPAL_CLIENT_SECRET": "b"})
    assert not live_ready({"PAYPAL_CLIENT_ID": "a", "PAYPAL_CLIENT_SECRET": "b", "PAYPAL_ENV": "live"})
