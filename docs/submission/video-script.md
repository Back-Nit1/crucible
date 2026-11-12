# Demo video script (target 2:40, hard limit under 3:00)

> **ARCHIVED 2026-11-12.** Hackathon demo-video script, never recorded or submitted. Kept for reference only.

**Requirements:** under 3 minutes; public on YouTube; English; **demo mode on** (`DEMO_MODE=1`, brand names show as `[brand hidden]`); no third-party trademarks or copyrighted music (no music at all, or music you composed or licensed). Show only our UI, PayPal's own sandbox pages (required to show the approval) and the terminal. Do not show the dataset's vendor logo or any product photo. Say "a public product-review dataset", not a brand name. Never show `.env`, tokens or the buyer password (type it off-screen or blur it; use the sandbox buyer only).

**Honesty rule for the narration:** no model has run. Do not say the model was trained, evaluated or improved. Say exactly what was built and measured (numbers from the files cited). If the model endpoint gets enabled before recording, use shot block B2 instead of B1 and record the real result.

Screen: 1440x900 browser, dark UI, cursor visible, no notifications. Narration in a steady, plain voice; times are cumulative.

| # | Time | On screen (exact actions) | Narration |
|---|---|---|---|
| 1 | 0:00-0:15 | `https://crucible-2rcx.onrender.com/world` with the page title and the amber "Pipeline evidence only" banner visible. Slow scroll to the metric cards. | "Crucible is an evolutionary RL world for training an open model to shop on PayPal. Agents compete on seeded tasks over a frozen product-review snapshot. Kill rules remove cheaters, and every purchase ends in a PayPal sandbox checkout." |
| 2 | 0:15-0:40 | Same page: point at Population 8, Episodes 96, Survivors 3, Budget charged 0. Scroll to "Kills by rule" (K001 12, K002 18, K004 21, K003 5, K008 9). | "This is a real generation: eight agents, ninety-six episodes, traced in Elastic. Thirty-five episodes were killed by rule. Four of the eight agents were planted to cheat, to prove each guard fires. Zero budget violations were charged; five attempts were blocked at the payment guard. These shoppers are scripted and read the answer key, so this is pipeline evidence, not model performance." |
| 3 | 0:40-1:05 | Click **Episodes**. Sort by fitness, filter killed = true. Click one killed row to open the replay: show the ordered steps, then the kill rule and its evidence. | "Every decision is auditable. The AG Grid explorer sorts and filters server-side. Here is a killed episode: the ordered replay, the score, and the exact rule and evidence that ended it." |
| 4 | 1:05-1:20 | Click **Models**. Hold on the "Not run" states. | "The model dashboard says what we have not done: the Qwen probe, LoRA training and the before and after evaluation are not run yet, so they show Not run, not a made-up number." |
| 5 | 1:20-1:30 | Switch to a terminal (large font). Run: `curl -s "https://crucible-api-t6pn.onrender.com/catalog/search?q=running%20shoes&max_price=100" \| head -c 600` | "Now the PayPal side. A catalog search over the frozen snapshot; brand names are masked in demo mode." |
| 6 | 1:30-1:50 | Terminal: run the `POST /purchase/propose` command from the README (Path A step 2). Highlight `total`, `quote_basis`, `approval_url`. | "Proposing a purchase creates a PayPal Orders v2 order against a verified quote and checks the budget on the quote total. Nothing is charged yet. PayPal returns an approval link." |
| 7 | 1:50-2:05 | Terminal: run `POST /purchase/confirm` with `"user_confirmed":false`, then `true` before approving. Show 428 `confirmation_required`, then 402 `payment_failed`. | "Confirmation is required, and capture is refused until the buyer has approved. These are the guards the world's kill rules also test." |
| 8 | 2:05-2:25 | Browser: open the `approval_url` (PayPal sandbox page). Log in as the sandbox buyer (credentials off-screen), click the pay button, land back on `https://crucible-2rcx.onrender.com/payments`. | "The buyer approves on PayPal's own sandbox page. This is the sandbox: no real money." |
| 9 | 2:25-2:40 | Terminal: run `POST /purchase/confirm` with `"user_confirmed":true`. Show `status: COMPLETED`, `order_id`, `capture_id`, amount. Then open the Payments page (or the order in the PayPal sandbox dashboard) and **end on the receipt / captured order**, held for 3 seconds. | "Confirmed: the order is captured exactly once, and the receipt shows the PayPal order and capture ids. The sandbox record is the source of truth. Crucible: evidence before action." |

Total narration is about 340 words (about 2:30 at a calm pace). If it runs long, cut shot 4.

## Alternative block B2 (only if the model endpoint is enabled: `https://crucible-api-t6pn.onrender.com/ready` shows `model_configured: true`)
Replace shots 5-7 (1:20-2:05) with: open `https://crucible-2rcx.onrender.com/`, type `I need comfortable over-ear headphones for long study sessions, under $120 all-in. I wear glasses, so pressure matters.`, press **Run grounded research**, scroll through the intent, research timeline, product cards (source and date), review evidence ids and the quote; select the quoted item. Narration: "A raw request becomes parsed intent, grounded research, cited review evidence and a verified quote. Nothing is purchased until I confirm." Then continue with shot 8. Record only what actually happens; if the agent says no realistic match, keep that: it is a correct outcome.

## Recordings the owner must capture (the assistant cannot record)
1. Shots 1-4: screen recording of the hosted `/world`, `/episodes` (with one killed-episode replay) and `/models`, dark mode, 1440x900.
2. Shots 5-7 and 9: terminal recording with a large font, using the exact commands in the README "Judge testing" Path A, with the real `https://crucible-api-t6pn.onrender.com`.
3. Shot 8: the PayPal sandbox approval page with the sandbox buyer (hide the password), and the redirect back to `/payments`.
4. Final receipt frame: the captured order (terminal JSON, `/payments`, or the PayPal sandbox dashboard).
5. Optional cut-in: the Kernel approval session recording ([`docs/spikes/paypal-kernel.md`](../spikes/paypal-kernel.md)), only if one succeeds; do not present it as reliable (1 of 8 runs).
6. Voice-over in English, no music; export 1080p or higher; upload to YouTube as **Public**; paste the URL into `<<YOUTUBE_URL>>` in the README and Devpost; check the length reads under 3:00 on YouTube.
7. Before recording: `DEMO_MODE=1` on the API, `PAYMENTS_BACKEND=sandbox`, `CORS_ALLOW_ORIGINS` set to the web origin, then `uv run python -m scripts.verify_deploy https://crucible-2rcx.onrender.com https://crucible-api-t6pn.onrender.com` must pass.
