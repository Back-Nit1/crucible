"""KernelApprover with a fake Kernel client: block detection, secret scrubbing, cleanup."""
from types import SimpleNamespace as NS

import pytest

from payments.kernel_approver import ApprovalBlocked, KernelApprover


class FakeKernel:
    def __init__(self, result=None, error=None):
        self.deleted, self.code = [], None
        self._res = NS(success=error is None, result=result, error=error)
        self.browsers = NS(create=lambda **kw: NS(session_id="sess"),
                           delete_by_id=self.deleted.append,
                           playwright=NS(execute=self._exec))

    def _exec(self, sid, code, timeout_sec):
        self.code = code
        return self._res


class FakeBackend:
    def __init__(self, statuses):
        self.statuses = iter(statuses)

    def approval_url(self, oid):
        return "https://sandbox.example/pay"

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
