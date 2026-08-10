# Work Smarter, Not Harder — demo video script & shot-list

> **Which video is this?** The **graded submission video** — 3–5 min, with voiceover, mapped to the rubric,
> filed as `VID_<id1>_<id2>_<id3>.mp4`. It is one of the three required hand-in items (repo link · video ·
> report) and is **not yet recorded**.
>
> It is **not** the Show Off gallery clip. That one is separate, 20–90 s and **silent**, already cut as
> `presentation/showoff/demo.mp4` (27.9 s) and submitted on 29 Jul. Don't confuse the two: this script's
> voiceover column would disqualify the gallery clip, and the gallery clip is far too short for this.

**Goal:** in one continuous take, show *every* graded item working on the **live** site
(https://app.worksmarternotharder.dev). Target length **3–5 min**. Each shot below names what to click, what to
say, and **which rubric item it proves** — so a TA can tick every box.

> Record at 1080p, browser only (hide bookmarks). Have **two accounts** ready for the DM / notification shots —
> and note that prod runs with **live email**, so the second account needs a real mailbox to clear the
> verification code. The model landed 11–12 Jul, so shot 3 is filmed in full; state the readiness state and the
> calorie target, but still no accuracy figure (we have not published one).

| # | Shot / action | Say (voiceover) | Proves (rubric) |
|---|---|---|---|
| 0 | The **live URL** in the address bar; padlock visible | "This is running live on Azure over HTTPS — not localhost." | Deployment (+10), HTTPS |
| 1 | **Register** → enter email → **email-verification code** screen → verify → you're in | "Sign-up verifies the email before the account exists — no fake or borrowed addresses." | Build (auth), security |
| 2 | **Log out → log in** → **2-step code** screen → enter code → in | "Login is two-factor: password, then a one-time code." | Build (auth), security |
| 3 | **Daily check-in** → fill **all five**: sleep · resting HR · **fatigue** · soreness · training load → **Submit** → the **readiness ring** (Ready/Moderate/Rest) + recommendation + calories | "One morning check-in → a readiness state, a recommendation, and a calorie target — from the local model." | Build (the core product), AI |
| 4 | **History** tab → the past check-ins / trend | "Every check-in is persisted and trended." | Build (persistence) |
| 5 | **Forum** → create a **post** with a **title + body + image** | "The forum: posts with image and video attachments…" | Forum #1 |
| 6 | Add a **comment** (text); **like/dislike** the post and the comment; show the **per-item 👍/👎 counts** on the row, the detail and the comment | "…comments on every post, and like/dislike on both, with the counts on each." | Forum #2, #3 |
| 7 | Toggle **anonymous** on a post | "Posts can be anonymous — a bonus we kept." | Forum bonus (anonymity) |
| 8 | **Chat** → search a user → send a **DM** with an image → (switch to 2nd account) the DM **arrives with no refresh** + a **notification** | "Direct messages with media, delivered in real time — no refresh — and a notification fires." | Forum #4, #5, real-time |
| 9 | Back on account 1: a **notification** that account 2 liked your post | "Notifications for likes too." | Forum #5 |
| 10 | Try to **upload an oversized file** → rejected; (optional) rapid-fire posts → rate-limited | "Anti-abuse: file-size caps and anti-spam rate-limits." | Forum #6 (anti-abuse) |
| 11 | Mention the feed came **pre-seeded** (existing posts/users on first load) — prod already holds real content, so this needs no setup | "The forum launches cold-seeded with clients and history." | Forum #7 (cold-seeding) |
| 12 | **Add to Home Screen** on a phone (or show the installed PWA icon + splash) | "It installs as a phone app — its own icon and splash." | Build polish (PWA) |
| 13 | Cut to the **GitHub Actions** tab: a green run — the real job names are `checks` → `cross-container stack (test-runner)` → **`e2e (browser · desktop + mobile)`** → `build & push image (GHCR)` → `deploy to Azure VM` | "Every push runs the full suite, the cross-container stack **and** a real browser at two viewports; on green it auto-deploys." | CI/CD (+10) |
| 14 | Show the **job queue**. ⚠️ **Not from the browser** — `/queue/stats` lives on the `ai` container, which has no `ports:` and is deliberately unreachable from outside (only `web` is exposed; that isolation is itself a graded requirement). Film **one** of: a terminal running `docker compose exec ai curl -s localhost:5000/queue/stats` on the VM, or the measured numbers in `docs/DEMO_RUNBOOK.md` | "A bounded queue + a process pool work many predictions in parallel — measured 2.86× throughput at four workers. Only `web` is exposed, so this is read from inside the network." | Job Queue (+5), scaling, isolation |
| 15 | Close on the live URL | "Work Smarter, Not Harder — live, tested, and deployed." | wrap |

## Coverage checklist (tick before you publish)
- [ ] **75 build:** auth (1,2), core check-in→readiness (3), history (4), the app is clearly a working product.
- [ ] **+5 Job Queue:** shot 14 (queue + parallel + the scaling number).
- [ ] **+10 Forum:** shots 5–11 cover the built sub-features + real-time + anonymity bonus. **One is still not
      built — do not film it:** media on *comments* (#407). An attachment-only DM sends no notification
      (#408) — send text alongside the image. *(Per-item like/dislike counts were the second gap; #409 closed
      31 Jul and the counts now render on the row, the detail and each comment — film them.)*
- [ ] **+10 Azure/CI-CD:** shot 0 (live HTTPS) + shot 13 (pipeline test-on-commit → auto-deploy).
- [ ] **Security posture:** email-verify (1), 2FA (2), file-size/rate-limit (10), HTTPS (0).

## Beauty pass (class-vote differentiator — the app now LOOKS finished)
The 5-min pitch is judged partly by a class vote, and a polished product reads as "done." The design pass is
shipped and live, so let the visuals sell it in passing — no extra shots, just don't rush past them:
- **Shot 0 / 3:** linger a beat on the **readiness ring** — the big 0–100 score **counts up** into place as the
  ring fills (Whoop/Oura style). It's the signature moment; let it land.
- **Shots 5–8 (forum + chat):** the **generative avatars** (each person a consistent colour) and the WhatsApp-style
  chat (day separators, timestamps, "Seen") read as a real app — worth a slow scroll, not a fast click.
- **Any screen:** it's a **theme-aware installable PWA** with calm, restrained motion (one accent, solid cards,
  SVG icons) — the opposite of an "AI-generated" look. One line in the voiceover ("and it's a finished, designed
  product, not a prototype") is enough.

## Production tips
- One take if you can; if not, cut on tab-switches so it still feels continuous.
- Keep the voiceover to the "Say" column — it's already timed to ~4 min.
- Name the file `VID_<id1>_<id2>_<id3>.mp4` to match the submission convention.
- Shot 14 cannot be filmed in the browser — see its row. Decide the terminal-vs-report option before you start,
  so you are not improvising mid-take.

## Still outstanding
- **[ FILL IN ] The video itself** — not recorded. Save the final cut as `VID_<id1>_<id2>_<id3>.mp4`.

*(Two former placeholders are resolved: shot 3 no longer waits on the model, which landed 11–12 Jul; and shot 11
needs no setup, because prod already holds real posts and users. Seeding a **fresh** clone is `./seed.sh` — worth
knowing, because `install.sh` alone leaves a reviewer with an empty forum.)*
