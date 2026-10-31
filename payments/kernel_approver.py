"""Spike: approve a sandbox order as the sandbox *personal (buyer)* account in a Kernel browser.

Kernel docs: https://www.kernel.sh/docs/quickstart (browsers.create, browsers.playwright.execute).
Deliberately default browser: no stealth, no proxy, no CAPTCHA solving. Any challenge raises
ApprovalBlocked and the run stops (spec 7.1). Buyer credentials are only ever sent to Kernel
inside the Playwright call and are scrubbed from any error text."""
import json
import time

from payments.sandbox import SandboxPayments

_BLOCK = r"/captcha|verify you.re (a )?human|unusual activity|security challenge|confirm you.re not a robot|robot/i"

# One Playwright body, run inside the Kernel VM (`page` is provided). Stage-by-stage so a
# challenge is reported where it happened. Selectors verified against the live sandbox login page.
_JS = """
const blocked = async (stage) => {
  const txt = (await page.innerText('body').catch(() => '')) || '';
  const chal = await page.locator('iframe[src*="recaptcha"][title*="challenge" i], iframe[src*="hcaptcha"], iframe[src*="arkose"]').first().isVisible().catch(() => false);
  return (chal || %(block)s.test(txt)) ? {blocked: true, stage} : null;
};
await page.goto(%(url)s, {waitUntil: 'domcontentloaded'});
let b = await blocked('landing'); if (b) return b;
await page.fill('#email', %(email)s);
if (await page.locator('#password').isVisible()) {} else { await page.click('#btnNext'); await page.waitForSelector('#password', {state: 'visible', timeout: 20000}); }
await page.fill('#password', %(password)s);
await page.click('#btnLogin');
await page.waitForTimeout(4000);
b = await blocked('after_login'); if (b) return b;
const done = /Complete Purchase|Pay Now|Continue|Agree/i;
const btn = page.getByRole('button', {name: done}).first();
await btn.waitFor({state: 'visible', timeout: 30000});
await btn.click();
await page.waitForLoadState('domcontentloaded');
await page.waitForTimeout(3000);
b = await blocked('after_review'); if (b) return b;
return {blocked: false, host: new URL(page.url()).host};
"""


class ApprovalBlocked(Exception):
    """Challenge / bot check / unexpected page. Report; do not work around."""


class KernelApprover:
    def __init__(self, backend: SandboxPayments, email: str, password: str, kernel=None):
        if kernel is None:
            from kernel import Kernel  # optional dep: `uv sync --extra kernel`
            kernel = Kernel()
        self._k, self._b, self._cred = kernel, backend, (email, password)
        self.timings: dict[str, float] = {}

    def approve(self, order_id: str, timeout: float = 60) -> str:
        """Drive the buyer approval; returns the order status once APPROVED."""
        start = time.perf_counter()
        browser = self._k.browsers.create(timeout_seconds=180)  # defaults: no stealth, no proxy
        self.timings["browser_create"] = time.perf_counter() - start
        try:
            code = _JS % {"block": _BLOCK, "url": json.dumps(self._b.approval_url(order_id)),
                          "email": json.dumps(self._cred[0]), "password": json.dumps(self._cred[1])}
            t = time.perf_counter()
            r = self._k.browsers.playwright.execute(browser.session_id, code=code, timeout_sec=90)
            self.timings["browser_flow"] = time.perf_counter() - t
            if not r.success:
                raise ApprovalBlocked(self._scrub(f"browser step failed: {r.error}"))
            if r.result.get("blocked"):
                raise ApprovalBlocked(f"challenge detected at {r.result['stage']}")
        finally:
            self._k.browsers.delete_by_id(browser.session_id)
        deadline = time.monotonic() + timeout
        while (status := self._b.get_status(order_id)) != "APPROVED":
            if time.monotonic() > deadline:
                raise ApprovalBlocked(f"order still {status} after browser flow")
            time.sleep(1)
        self.timings["total"] = time.perf_counter() - start
        return status

    def _scrub(self, text: str) -> str:
        for secret in self._cred:
            text = text.replace(secret, "***")
        return text
