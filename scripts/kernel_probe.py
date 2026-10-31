"""Credential-free probe: open our own sandbox approval page in a default (no stealth, no proxy)
Kernel browser and report page structure/block signals. Never prints the URL."""
import sys, time, json
sys.path.insert(0, "scripts")
from decimal import Decimal
from _env import load
load(sys.argv[1], {"PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "PAYPAL_ENV", "KERNEL_API_KEY"})
from kernel import Kernel
from payments.sandbox import SandboxPayments

sb = SandboxPayments()
oid = sb.create_order(Decimal("1.00"), "USD", f"probe-{time.time_ns()}")
k = Kernel()
t = time.perf_counter()
b = k.browsers.create(timeout_seconds=180)
print("browser_create_ms", round((time.perf_counter() - t) * 1000), "stealth", b.stealth, "headless", b.headless)
code = """
await page.goto(%s, {waitUntil: 'domcontentloaded'});
await page.waitForTimeout(4000);
const txt = (await page.innerText('body')).slice(0, 4000);
return {host: new URL(page.url()).host, path: new URL(page.url()).pathname, title: await page.title(),
  inputs: await page.$$eval('input:not([type=hidden])', els => els.map(e => ({id: e.id, name: e.name, type: e.type}))),
  buttons: await page.$$eval('button, [role=button]', els => els.map(e => ({id: e.id, text: (e.innerText||'').trim().slice(0, 40), tid: e.getAttribute('data-testid')}))),
  frames: page.frames().map(f => new URL(f.url()).host),
  blockWords: /captcha|verify you.re (a )?human|unusual activity|security challenge|robot/i.test(txt)};
""" % json.dumps(sb.approval_url(oid))
try:
    r = k.browsers.playwright.execute(b.session_id, code=code, timeout_sec=60)
    print("success", r.success, json.dumps(r.result)[:2500], r.error)
finally:
    k.browsers.delete_by_id(b.session_id)
print("order_status_after", sb.get_status(oid))
