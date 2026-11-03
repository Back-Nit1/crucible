"""KernelApprover with a fake Kernel client: block detection, secret scrubbing, cleanup."""
from types import SimpleNamespace as NS

import pytest

from payments.kernel_approver import (AUTH_ENV, ApprovalBlocked, ApprovalNotAuthorized, KernelApprover, KernelError,
                                      check_approval_url)


@pytest.fixture(autouse=True)
def authorized(monkeypatch):
    monkeypatch.setenv(AUTH_ENV, "1")


class FakeKernel:
    def __init__(self, result=None, error=None):
        self.deleted, self.code, self.created = [], None, 0
        self._res = NS(success=error is None, result=result, error=error)
        self.browsers = NS(create=self._create,
                           delete_by_id=self.deleted.append,
                           playwright=NS(execute=self._exec))

    def _create(self, **kw):
        self.created += 1
        return NS(session_id="sess")

    def _exec(self, sid, code, timeout_sec):
        self.code = code
        if isinstance(self._res.error, Exception):
            raise self._res.error
        return self._res


class FakeBackend:
    def __init__(self, statuses):
        self.statuses = iter(statuses)

    url = "https://www.sandbox.paypal.com/checkoutnow?token=T"

    def approval_url(self, oid):
        return self.url

    def get_status(self, oid):
        return next(self.statuses)


def test_approves_and_always_deletes_browser():
    k = FakeKernel({"blocked": False})
    a = KernelApprover(FakeBackend(["APPROVED"]), "b@x.test", "pw", kernel=k)
    assert a.approve("O1") == "APPROVED" and k.deleted == ["sess"]
    assert "stealth" not in k.code and "proxy" not in k.code


def test_challenge_stops_run():
    k = FakeKernel({"blocked": True, "stage": "after_login"})
    with pytest.raises(ApprovalBlocked, match="after_login"):
        KernelApprover(FakeBackend([]), "b@x.test", "pw", kernel=k).approve("O1")
    assert k.deleted == ["sess"]


def test_errors_never_contain_credentials():
    k = FakeKernel(error="timeout waiting for fill of hunter2")
    with pytest.raises(ApprovalBlocked) as e:
        KernelApprover(FakeBackend([]), "b@x.test", "hunter2", kernel=k).approve("O1")
    assert "hunter2" not in str(e.value)


def approver(backend=None, kernel=None, **kw):
    return KernelApprover(backend or FakeBackend(["APPROVED"]), "b@x.test", "pw", kernel=kernel or FakeKernel({"blocked": False}), **kw)


def test_no_browser_without_explicit_authorization(monkeypatch):
    monkeypatch.delenv(AUTH_ENV)
    k = FakeKernel({"blocked": False})
    with pytest.raises(ApprovalNotAuthorized):
        KernelApprover(FakeBackend(["APPROVED"]), "b@x.test", "pw", kernel=k)
    with pytest.raises(ApprovalNotAuthorized):  # also before the SDK would even be imported
        KernelApprover(FakeBackend(["APPROVED"]), "b@x.test", "pw")
    monkeypatch.setenv(AUTH_ENV, "yes")
    with pytest.raises(ApprovalNotAuthorized):
        approver()
    assert k.created == 0


def test_missing_buyer_credentials_fail_closed():
    with pytest.raises(ApprovalNotAuthorized):
        KernelApprover(FakeBackend([]), "", "pw", kernel=FakeKernel({"blocked": False}))


@pytest.mark.parametrize("url", ["https://www.sandbox.paypal.com/checkoutnow?token=T", "https://sandbox.paypal.com/x"])
def test_allowlisted_sandbox_urls_pass(url):
    assert check_approval_url(url) == url


@pytest.mark.parametrize("url", [
    "https://www.paypal.com/checkoutnow?token=T",             # production host
    "http://www.sandbox.paypal.com/checkoutnow",              # not https
    "https://www.sandbox.paypal.com.evil.test/checkoutnow",   # suffix trick
    "https://evil.test/www.sandbox.paypal.com",
    "https://www.sandbox.paypal.com@evil.test/x",             # userinfo trick
    "https://www.sandbox.paypal.com:8443/x", "javascript:alert(1)", ""])
def test_everything_else_is_refused_before_a_browser_exists(url):
    k = FakeKernel({"blocked": False})
    b = FakeBackend(["APPROVED"])
    b.url = url
    with pytest.raises(ApprovalBlocked, match="allowlist"):
        approver(b, k).approve("O1")
    assert k.created == 0 and k.code is None


def test_flow_is_bounded_never_captures_and_enforces_host_in_browser():
    k = FakeKernel({"blocked": False})
    approver(kernel=k).approve("O1")
    code = "\n".join(l for l in k.code.splitlines() if not l.strip().startswith("//"))
    assert "/capture" not in code and "/v2/" not in code
    assert "/v2/" not in k.code and "fetch(" not in k.code and "api-m." not in k.code
    assert "sandbox\\.paypal\\.com" in k.code and "unexpected_host" in k.code and "stealth" not in k.code


@pytest.mark.parametrize("stage", ["landing", "after_login:unexpected_host", "after_review"])
def test_unexpected_challenge_or_host_stops_the_run_and_cleans_up(stage):
    k = FakeKernel({"blocked": True, "stage": stage})
    with pytest.raises(ApprovalBlocked, match=stage):
        approver(kernel=k).approve("O1")
    assert k.deleted == ["sess"]


def test_cleanup_happens_on_transport_failure_and_never_masks_the_outcome():
    k = FakeKernel(error=RuntimeError("socket hunter2 closed"))
    a = approver(kernel=k)
    a._cred = ("b@x.test", "hunter2")
    with pytest.raises(KernelError) as e:
        a.approve("O1")
    assert "hunter2" not in str(e.value) and k.deleted == ["sess"] and a.cleanup_ok is True
    k = FakeKernel({"blocked": True, "stage": "landing"})
    k.browsers.delete_by_id = lambda sid: (_ for _ in ()).throw(RuntimeError("delete failed"))
    a = approver(kernel=k)
    with pytest.raises(ApprovalBlocked):
        a.approve("O1")
    assert a.cleanup_ok is False


def test_create_failure_is_a_typed_kernel_error():
    k = FakeKernel({"blocked": False})
    k.browsers.create = lambda **kw: (_ for _ in ()).throw(ConnectionError("boom pw"))
    with pytest.raises(KernelError):
        approver(kernel=k).approve("O1")


def test_approval_is_verified_through_the_api_and_must_not_be_a_capture():
    with pytest.raises(ApprovalBlocked, match="unexpected order status COMPLETED"):
        approver(FakeBackend(["COMPLETED"])).approve("O1")
    with pytest.raises(ApprovalBlocked, match="still PAYER_ACTION_REQUIRED"):
        approver(FakeBackend(["PAYER_ACTION_REQUIRED"] * 5), sleep=lambda _: None).approve("O1", timeout=0)
    a = approver(FakeBackend(["PAYER_ACTION_REQUIRED", "APPROVED"]), sleep=lambda _: None)
    assert a.approve("O1") == "APPROVED" and {"browser_create", "browser_flow", "total"} <= set(a.timings)


def test_login_flow_uses_role_buttons_next_retry_and_one_time_cta():
    k = FakeKernel({"blocked": False})
    approver(kernel=k).approve("O1")
    assert "#btnNext" not in k.code and "#btnLogin" not in k.code  # ids do not exist on the live page
    assert "getByRole('button', {name: /^(Next|Seguinte|Pr[óo]ximo)$/i})" in k.code and "getByRole('button', {name: /^(Log ?In|Entrar)$/i})" in k.code
    assert k.code.count("await next.click()") == 2  # second click covers a click that landed before hydration
    assert "setExtraHTTPHeaders({'Accept-Language': 'en-US" in k.code  # login page was served in Portuguese once
    assert "timeout: 8000" in k.code and "timeout: 15000" in k.code
    assert "page.locator('#one-time-cta').or(" in k.code  # old regex kept as fallback


def test_pay_button_failure_reports_pathname_and_body_excerpt_scrubbed_of_credentials():
    k = FakeKernel(error="pay button not found at /pay: logged in as b@x.test pw hunter2")
    a = approver(kernel=k)
    a._cred = ("b@x.test", "hunter2")
    with pytest.raises(ApprovalBlocked) as e:
        a.approve("O1")
    assert "pay button not found at /pay" in str(e.value) and "hunter2" not in str(e.value) and "b@x.test" not in str(e.value)
    k = FakeKernel({"blocked": False})
    approver(kernel=k).approve("O1")
    assert "pay button not found at" in k.code and ".slice(0, 300)" in k.code
