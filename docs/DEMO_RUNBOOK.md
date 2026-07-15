# Demo Runbook — Work Smarter, Not Harder

Live-demo run-of-show for the class presentation (16 July 2026). Covers the pre-flight checklist,
the flow to show, fallbacks if something misbehaves, and the engineering talking points.

App: <https://app.worksmarternotharder.dev> · Accounts seeded for the demo: **liorbs1998** and **ELAD**.

---

## Before the demo

- [ ] **Start the VM ~1h ahead.** It auto-shuts-down daily (~23:50 UTC):
  ```bash
  az vm start -n sweng-group_02 -g SWENG-GROUP_02
  ```
  (Lior has Azure-portal access under subscription "DDS - 095219 (EA)" for a manual Restart if needed.)
- [ ] Open the app and **log in as `liorbs1998`**.
- [ ] **Do a fresh check-in.** The seeded "today" check-in reads as *yesterday* after midnight, so the
  "Check in for today" nudge shows — a live check-in clears it *and* demonstrates the readiness compute
  on screen (the orb animating to a 0–100 score).
- [ ] Have a **second device / browser logged in as `ELAD`** — this drives the real-time "wow".
- [ ] Hard-refresh once (clear cache/service worker) so you're on the latest deploy.

---

## Run-of-show (the live slice)

1. **Today / Readiness** — the breathing readiness orb, the streak, the AI recommendations.
   Do the live check-in → watch the orb compute a band-consistent 0–100 readiness score.
   > *"Readiness is scored by our Random Forest model, served from a separate AI container through a job queue."*

2. **History** — the trend sparkline + the 8-week readiness heatmap.
   > *"Every check-in persists to MongoDB; the heatmap is real data over 8 weeks."*

3. **Forum** — post something live. **Then the wow:** on the ELAD device, post / comment / vote →
   it appears on the main screen **instantly, with no refresh and no flicker**.
   > *"Real-time via Server-Sent Events — one persistent connection, a DB-backed revision counter so it
   > broadcasts across workers. The same backbone powers chat and notifications."*

4. **Chat / DM** — send a message from ELAD → it lands live on liorbs1998; show a media attachment
   (all of PNG / JPEG / WebP / GIF / MP4 are supported and persist across deploys).

5. *(if asked)* **Robustness** — see the talking points below.

---

## Fallbacks — never a blank screen

| If… | Do this |
|---|---|
| Real-time doesn't push instantly | Hit **Refresh** — the polling backstop still delivers within ~45s. |
| The VM is slow / wedged | **Azure portal → Restart** (the VM has 32 GB RAM, so it is *not* an OOM situation). |
| A deploy is mid-flight | The post-deploy health check + **auto-rollback** keeps the last good image serving. |
| A media file 404s | The persistent `media-data` volume (#294) means uploads survive redeploys — reload the post. |

---

## Engineering talking points (the story that lands)

- **Architecture** — 4 containers (web / ai / db / caddy) on an internal network; **Caddy is the only
  public surface**, terminating TLS with auto Let's Encrypt HTTPS.
- **Testing** — ~819 tests across unit / integration / system / security / stress. CI gates **every**
  merge (unit+integration → cross-container compose run → browser e2e on desktop *and* mobile), then
  auto-deploys to Azure.
- **Real-time** — Server-Sent Events for chat, notifications **and** the forum. No client polling on the
  happy path; polling is only the fallback.
- **Resilience** — 60s request timeout, graceful AI degradation (a page never crashes if the model is
  down), session-expiry → clean re-login, store outage → **503 (not a 500 crash)**, a global JSON error
  handler so the UI always gets a parseable reason, and **auto-rollback** on a failed deploy.
- **Scale** — measured **2.86× AI throughput** at 4 worker processes; rate limiting on mutating routes;
  load-tested with Locust.

---

## Team split (for credit)

- **Lior** — web application + the whole data layer + logging + containers + CI/CD + web/data tests.
- **Elad** — Azure deployment + the real-time backbone + rate limiting + stress testing.
- **Shiri** — the AI readiness model (Random Forest, recommendations, calorie targets).
