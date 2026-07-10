# Work Smarter, Not Harder — demo video script & shot-list

**Goal:** in one continuous take, show *every* graded item working on the **live** site
(https://app.worksmarternotharder.dev). Target length **3–5 min**. Each shot below names what to click, what to
say, and **which rubric item it proves** — so a TA can tick every box.

> Record at 1080p, browser only (hide bookmarks). Have **two accounts** ready (e.g. you + a second user) for the
> DM / notifications shots. If Shiri's model isn't final, keep shot 3 to "the pipeline returns a readiness signal"
> and don't state an accuracy figure.

| # | Shot / action | Say (voiceover) | Proves (rubric) |
|---|---|---|---|
| 0 | The **live URL** in the address bar; padlock visible | "This is running live on Azure over HTTPS — not localhost." | Deployment (+10), HTTPS |
| 1 | **Register** → enter email → **email-verification code** screen → verify → you're in | "Sign-up verifies the email before the account exists — no fake or borrowed addresses." | Build (auth), security |
| 2 | **Log out → log in** → **2-step code** screen → enter code → in | "Login is two-factor: password, then a one-time code." | Build (auth), security |
| 3 | **Daily check-in** → fill sleep / HR / soreness / load → **Submit** → the **readiness ring** (Ready/Moderate/Rest) + recommendation + calories | "One morning check-in → a readiness state, a recommendation, and a calorie target — from the local model." | Build (the core product), AI |
| 4 | **History** tab → the past check-ins / trend | "Every check-in is persisted and trended." | Build (persistence) |
| 5 | **Forum** → create a **post** with a **title + body + image** | "The forum: posts with image and video attachments…" | Forum #1 |
| 6 | Add a **comment** with an image; **like** the post and the comment; show the **counts** | "…comments with media, and like/dislike on both, with counts." | Forum #2, #3 |
| 7 | Toggle **anonymous** on a post | "Posts can be anonymous — a bonus we kept." | Forum bonus (anonymity) |
| 8 | **Chat** → search a user → send a **DM** with an image → (switch to 2nd account) the DM **arrives with no refresh** + a **notification** | "Direct messages with media, delivered in real time — no refresh — and a notification fires." | Forum #4, #5, real-time |
| 9 | Back on account 1: a **notification** that account 2 liked your post | "Notifications for likes too." | Forum #5 |
| 10 | Try to **upload an oversized file** → rejected; (optional) rapid-fire posts → rate-limited | "Anti-abuse: file-size caps and anti-spam rate-limits." | Forum #6 (anti-abuse) |
| 11 | Mention the feed came **pre-seeded** (existing posts/users on first load) | "The forum launches cold-seeded with clients and history." | Forum #7 (cold-seeding) |
| 12 | **Add to Home Screen** on a phone (or show the installed PWA icon + splash) | "It installs as a phone app — its own icon and splash." | Build polish (PWA) |
| 13 | Cut to the **GitHub Actions** tab: a green run — `checks → compose-e2e → build → deploy` | "Every push runs all the tests and the cross-container stack; on green it auto-deploys." | CI/CD (+10) |
| 14 | Show the **job queue** briefly: `GET /queue/stats` (or the scaling report) + say the numbers | "A bounded queue + a process pool work many predictions in parallel — measured 2.86× on the pool." | Job Queue (+5), scaling |
| 15 | Close on the live URL | "Work Smarter, Not Harder — live, tested, and deployed." | wrap |

## Coverage checklist (tick before you publish)
- [ ] **75 build:** auth (1,2), core check-in→readiness (3), history (4), the app is clearly a working product.
- [ ] **+5 Job Queue:** shot 14 (queue + parallel + the scaling number).
- [ ] **+10 Forum:** shots 5–11 cover all seven sub-features + real-time + anonymity bonus.
- [ ] **+10 Azure/CI-CD:** shot 0 (live HTTPS) + shot 13 (pipeline test-on-commit → auto-deploy).
- [ ] **Security posture:** email-verify (1), 2FA (2), file-size/rate-limit (10), HTTPS (0).

## Production tips
- One take if you can; if not, cut on tab-switches so it still feels continuous.
- Keep the voiceover to the "Say" column — it's already timed to ~4 min.
- Name the file `VID_<id1>_<id2>_<id3>.mp4` to match the submission convention.
- If a shot needs the model and it isn't ready, record everything else and drop shot 3 to "the pipeline returns
  a readiness signal" — re-record 3 once Shiri's model lands.

## Placeholders — not recorded / model-dependent
- **[ FILL IN ] Shot 3 (readiness):** depends on Shiri's model. Until it's trained, record it as "the pipeline
  returns a readiness signal" (no accuracy claim); re-record once the model lands.
- **[ FILL IN ] Shot 11 (cold-seeding):** shows only if the forum has seed content (Shiri's task). If it's
  empty, create a couple of posts manually just for the shot, and note seeding is pending.
- **[ FILL IN ] The video itself** — not recorded yet. Save the final cut as `VID_<id1>_<id2>_<id3>.mp4`.
