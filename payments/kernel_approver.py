"""Spike: approve a sandbox order as the sandbox *personal (buyer)* account in a Kernel browser.

Kernel docs: https://www.kernel.sh/docs/quickstart (browsers.create, browsers.playwright.execute).
Deliberately default browser: no stealth, no proxy, no CAPTCHA solving. Any challenge raises
ApprovalBlocked and the run stops (spec 7.1). Buyer credentials are only ever sent to Kernel
inside the Playwright call and are scrubbed from any error text."""
import json
import os
import time
from urllib.parse import urlsplit

from payments.sandbox import SandboxPayments

AUTH_ENV = "CRUCIBLE_KERNEL_BUYER_APPROVAL_AUTHORIZED"  # must be "1": no browser is created without it
ALLOWED_HOSTS = ("www.sandbox.paypal.com", "sandbox.paypal.com")  # the only hosts this automation may touch
_HOST_RE = r"/^(www\.)?sandbox\.paypal\.com$/"  # same allowlist, enforced inside the browser after every step
_BLOCK = (r"/captcha|verify you.re (a )?human|unusual activity|security challenge|confirm you.re not a robot|robot"
          r"|verify your identity|confirm your identity|security code|one-time (code|passcode)|two-step|2-step|enter the code/i")

# One Playwright body, run inside the Kernel VM (`page` is provided). Stage-by-stage so a
# challenge is reported where it happened. Selectors verified against the live sandbox login page.
_JS = """
const hostOk = () => { try { return %(host)s.test(new URL(page.url()).host); } catch (e) { return false; } };
const blocked = async (stage) => {
  if (!hostOk()) return {blocked: true, stage: stage + ':unexpected_host'};
  const txt = (await page.innerText('body').catch(() => '')) || '';
  const chal = await page.locator('iframe[src*="recaptcha"][title*="challenge" i], iframe[src*="hcaptcha"], iframe[src*="arkose"]').first().isVisible().catch(() => false);
  return (chal || %(block)s.test(txt)) ? {blocked: true, stage} : null;
};
await page.setExtraHTTPHeaders({'Accept-Language': 'en-US,en;q=0.9'});  // Kernel's IP geo served the login in Portuguese; the matchers below are English
await page.goto(%(url)s, {waitUntil: 'domcontentloaded'});
let b = await blocked('landing'); if (b) return b;
await page.waitForLoadState('networkidle', {timeout: 10000}).catch(() => {});  // let the SPA hydrate before typing
// Buttons have no ids on the live page: find them by role. A click or fill before hydration can reset the form to the email step, so retry the whole login up to 3 times.
const next = page.getByRole('button', {name: /^(Next|Seguinte|Pr[óo]ximo)$/i});
const login = page.getByRole('button', {name: /^(Log ?In|Entrar)$/i});
const diag = async (what) => {  // page pathname + body excerpt; the caller scrubs buyer credentials
  const t = ((await page.innerText('body').catch(() => '')) || '').replace(/\\s+/g, ' ').slice(0, 300);
  throw new Error(what + ' not found at ' + new URL(page.url()).pathname + ': ' + t);
};
for (let attempt = 1; ; attempt++) {
  if (!(await page.locator('#password').isVisible())) {
    await page.fill('#email', %(email)s);
    if (await next.isVisible().catch(() => false)) await next.click();
    if (!(await page.waitForSelector('#password', {state: 'visible', timeout: 8000}).catch(() => null))) {
      if (await next.isVisible().catch(() => false)) await next.click();
      await page.waitForSelector('#password', {state: 'visible', timeout: 15000}).catch(() => diag('password field'));
    }
  }
  await page.fill('#password', %(password)s);
  if (await login.waitFor({state: 'visible', timeout: 8000}).then(() => true, () => false)) break;
  if (attempt >= 3) await diag('login button');
}
await login.click();
await page.waitForTimeout(4000);
b = await blocked('after_login'); if (b) return b;
const done = /Complete Purchase|Pay Now|Continue|Agree/i;
// The button below approves the order as the buyer (PAY_NOW). Capture is never done here: the server captures via Orders v2.
const btn = page.locator('#one-time-cta').or(page.getByRole('button', {name: done})).first();
await btn.waitFor({state: 'visible', timeout: 30000}).catch(() => diag('pay button'));
await btn.click();
await page.waitForLoadState('domcontentloaded');
await page.waitForTimeout(3000);
// Paying redirects to the merchant return_url (not a challenge); the PayPal API status is the proof of approval.
if (new URL(page.url()).hostname !== %(ret)s) { b = await blocked('after_review'); if (b) return b; }
return {blocked: false, host: new URL(page.url()).host};
"""


class ApprovalBlocked(Exception):
    """Challenge / bot check / unexpected page or host. Report; do not work around."""


class ApprovalNotAuthorized(Exception):
    """Browser automation was not explicitly authorized. Nothing was launched."""


class KernelError(Exception):
    """Kernel API / transport failure (not a PayPal challenge). Text is scrubbed of buyer credentials."""


def check_approval_url(url: str) -> str:
    """Only an https PayPal *sandbox* URL, no userinfo/port tricks, may ever be navigated to."""
    u = urlsplit(url)
    if u.scheme != "https" or u.hostname not in ALLOWED_HOSTS or u.username or u.password or u.port not in (None, 443):
        raise ApprovalBlocked("approval url host is not on the PayPal sandbox allowlist")
    return url


class KernelApprover:
    def __init__(self, backend: SandboxPayments, email: str, password: str, kernel=None, sleep=time.sleep):
        if os.environ.get(AUTH_ENV) != "1":  # checked before the SDK is imported or any session exists
            raise ApprovalNotAuthorized(f"set {AUTH_ENV}=1 to allow Kernel sandbox buyer approval")
        if not (email and password):
            raise ApprovalNotAuthorized("sandbox buyer credentials missing")
        if kernel is None:
            from kernel import Kernel  # optional dep: `uv sync --extra kernel`
            kernel = Kernel()
        self._k, self._b, self._cred, self._sleep = kernel, backend, (email, password), sleep
        self.timings: dict[str, float] = {}
        self.cleanup_ok: bool | None = None

    def approve(self, order_id: str, timeout: float = 60) -> str:
        """Drive the buyer approval; returns the order status once APPROVED (verified through the PayPal API)."""
        start = time.perf_counter()
        url = check_approval_url(self._b.approval_url(order_id))  # allowlist BEFORE any browser exists
        try:
            browser = self._k.browsers.create(timeout_seconds=180)  # defaults: no stealth, no proxy
        except Exception as e:
            raise KernelError(self._scrub(f"browser create failed: {type(e).__name__}")) from None
        self.timings["browser_create"] = time.perf_counter() - start
        try:
            code = _JS % {"block": _BLOCK, "host": _HOST_RE, "ret": json.dumps(self._return_host()), "url": json.dumps(url),
                          "email": json.dumps(self._cred[0]), "password": json.dumps(self._cred[1])}
            t = time.perf_counter()
            try:
                r = self._k.browsers.playwright.execute(browser.session_id, code=code, timeout_sec=90)
            except Exception as e:
                raise KernelError(self._scrub(f"browser step failed: {type(e).__name__}")) from None
            self.timings["browser_flow"] = time.perf_counter() - t
            if not r.success:
                raise ApprovalBlocked(self._scrub(f"browser step failed: {r.error}"))
            if r.result.get("blocked"):
                raise ApprovalBlocked(f"challenge detected at {r.result['stage']}")
        finally:
            try:
                self._k.browsers.delete_by_id(browser.session_id)
                self.cleanup_ok = True
            except Exception:  # never mask the real outcome; surfaced via cleanup_ok
                self.cleanup_ok = False
        deadline = time.monotonic() + timeout
        while (status := self._b.get_status(order_id)) != "APPROVED":
            if status in ("COMPLETED", "VOIDED"):
                raise ApprovalBlocked(f"unexpected order status {status} after browser flow")
            if time.monotonic() > deadline:
                raise ApprovalBlocked(f"order still {status} after browser flow")
            self._sleep(1)
        self.timings["total"] = time.perf_counter() - start
        return status

    def _return_host(self) -> str:
        return urlsplit(getattr(self._b, "return_url", "https://example.com/return")).hostname or ""

    def _scrub(self, text: str) -> str:
        for secret in self._cred:
            text = text.replace(secret, "***")
        return text
