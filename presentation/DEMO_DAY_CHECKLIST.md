# Demo Day — live-app stability runbook (Thu 16 Jul · slot 8 @ 9:15)

Deliverables, deck, and video live in **`WSNH Submission Checklist.md`**. This one page is *only* about
keeping the **live app** rock-solid for the 5-minute slot — so a background deploy can't 502 it mid-demo.

## The one risk
Every push to `main` auto-deploys, which recreates the `web`+`ai` containers → a **~30–60s window** where the
live site returns 502. Harmless day-to-day; only a problem if it lands *during* your slot.

## Optional freeze — do this ONLY if it's actually relevant on the day
**Skip it unless someone might merge to `main` close to your slot** — you're still landing last-minute fixes,
or a teammate / AI agent might push. If `main`'s been quiet and nobody's mid-merge, there's nothing to freeze;
just run the pre-slot check below and present.

If it *is* relevant, freeze (deploys skip; the live site keeps serving the current build; build + tests still run):
```
gh variable set DEPLOY_ENABLED -R LiorBenSidi/work-smarter-not-harder --body false
```
Unfreeze after the presentation:
```
gh variable set DEPLOY_ENABLED -R LiorBenSidi/work-smarter-not-harder --body true
```
Freeze **after** your last intended deploy, so the version that's live is the one you'll show.

## 5-minute pre-slot check (do these regardless)
- [ ] **VM is running** — the instructor VM auto-shuts at 23:50 UTC; Azure portal → Restart if it's off.
- [ ] **Live health** — `curl -s -w "\n%{http_code}\n" https://app.worksmarternotharder.dev/ready` → **200**.
- [ ] **Warm it up** — open the app once in the demo browser (log in, glance at Today) so nothing's cold.

## If it 502s anyway (recovery)
1. Wait ~30s and refresh — a redeploy blip self-heals once the container is healthy again.
2. Still down: `ssh -i ~/.ssh/deploy_private_key.txt azureuser@sweng-group-02.eastus.cloudapp.azure.com 'cd ~/app && docker compose -f docker-compose.prod.yml restart web ai'`
3. VM wedged / SSH hangs: Azure portal (subscription "DDS – 095219") → Restart the VM, then re-check `/ready`.
