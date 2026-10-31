"""Day-1 check 1a: sandbox OAuth. Prints sanitized fields only (never the token)."""
import sys, time
sys.path.insert(0, "scripts")
import httpx
from _env import load
load(sys.argv[1], {"PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "PAYPAL_ENV"})
import os
assert os.environ.get("PAYPAL_ENV", "sandbox") == "sandbox"
t = time.perf_counter()
r = httpx.post("https://api-m.sandbox.paypal.com/v1/oauth2/token",
               auth=(os.environ["PAYPAL_CLIENT_ID"], os.environ["PAYPAL_CLIENT_SECRET"]),
               data={"grant_type": "client_credentials"}, timeout=30)
ms = (time.perf_counter() - t) * 1000
b = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
print("status", r.status_code, "ms", round(ms), "keys", sorted(b), "token_type", b.get("token_type"),
      "expires_in", b.get("expires_in"), "access_token_len", len(b.get("access_token", "")))
if r.status_code != 200:
    print("error", b.get("error"), b.get("error_description"))
