# Work Smarter, Not Harder — demo video script & shot-list

> **Which video is this?** The **graded submission video** — with voiceover, mapped to the rubric, filed as
> `VID_<id1>_<id2>_<id3>.mp4`. It is one of the three required hand-in items (repo link · video · report) and
> is **not yet recorded**.
>
> It is **not** the Show Off gallery clip. That one is separate, 20–90 s and **silent**:
> `presentation/showoff/demo.mp4`, **57 s**, rebuilt from its own committed source
> (`presentation/showoff/demo.html` → `build-demo.sh`). Don't confuse the two — this script's voiceover
> would disqualify the gallery clip, and the gallery clip is far too short for this.

**Goal:** show *every* graded feature working on the **live** site (https://app.worksmarternotharder.dev).
The Moodle announcement asks for "a video of you using the app… you are **highly advised to demonstrate all of
the app's features**", so the shot list below is built feature-by-feature against `docs/REPORT.md` §2 — F1
through F9, then the Forum, CI/CD and job-queue extras. Target **4–6 min**.

> Record at 1080p, browser only (hide bookmarks). Have **two accounts** ready for the DM / notification shots —
> prod runs with **live email**, so the second account needs a real mailbox to clear the verification code.

### Seed the data first — `./seed.sh` alone is NOT enough

This is the same trap the poster hit. **`db/seed.py` seeds users, posts, comments and likes only — it does
not seed check-in history and it does not seed DM conversations.** On a freshly seeded clone, **shot 10**
(History: trend line + heatmap) shows a single cell and no trend, and **shot 16** (Chat) says *"No
conversations yet"*. Both shots die on camera.

The poster solved this with a second seeder, and the video needs it too:

```sh
./seed.sh                                    # users · posts · comments · likes
docker compose run --rm -v "$PWD:/repo" \
  -e MONGO_URI="mongodb://db:27017/worksmarter" \
  --entrypoint sh web -c 'exec python /repo/presentation/showoff/seed-for-screenshots.py'
```

The second command back-dates **49 daily check-ins** and creates a **DM thread with a seeded coach**, then
prints the athlete's login. Everything is written through the real `web/services/db.py` CRUD, so the rows are
shaped exactly like user-created ones.

**Filming on prod instead?** Then skip both — prod already holds real posts, users and history. Just confirm
the account you film with has a populated History tab **before** you start the take.

| # | Shot / action | Say (voiceover) | Proves |
|---|---|---|---|
| 0 | The **live URL** in the address bar; padlock visible | "This is running live on Azure over HTTPS — not localhost." | Deploy (+10), HTTPS |
| 1 | **Register** → enter email → **email-verification code** screen → verify → you're in | "Sign-up verifies the email before the account exists — no fake or borrowed addresses." | **F1**, security |
| 2 | **Log out → log in** → **2-step code** screen → enter code → in | "Login is two-factor: password, then a one-time code." | **F1**, security |
| 3 | **Profile & account** (user menu) → fill **age · gender · height · weight · goal**, set **sessions/week to 4**, leave split preference on **No preference**, then tap **several equipment chips** (Dumbbells · Barbell · Machines · Pull-up bar — not just Bodyweight) | "The athlete profile drives everything downstream — the calorie target, the readiness baseline, and which exercises the plan may use." | **F2** |
| 4 | Same screen, scroll to **"Your current training programme"** → enter a **deliberately unbalanced** week: **Chest 24 · Back 4 · Calves 2**, leave the rest blank → **Save** | "This is what you train *now* — weekly sets per muscle group. It's optional, and a blank group just means you don't train it." | **F6 (input)** |
| 5 | **Daily check-in** → fill **all five**: sleep · resting HR · fatigue · soreness · training load → **Submit** | "One morning check-in — five metrics." | **F3** (web path) |
| 6 | The **readiness ring** lands (Ready / Moderate / Rest) + the **confidence bars** + the **calorie target**, plus the **recommended weekly frequency** and the athlete's **current tier** | "A locally-trained Random Forest calls the readiness state, with its confidence, and a calorie target from Mifflin–St Jeor, plus the recommended weekly frequency and the athlete's current tier." | **F3** (model), **F4**, **F8** |
| 7 | Scroll the recommendation list — point out the **balance lines** that came from the programme entered in shot 4 ("chest volume is high relative to back…") | "And because it knows the programme, the advice isn't generic — it's reading actual weekly volume against balanced-training guidelines." | **F6 (output)**, **F7** |
| 8 | The **workout plan card** — because shot 3 set **4** sessions/week, it opens on the **split picker**: *"Two splits suit your week equally well."* Two buttons: **Full body** / **Upper / lower** | "At four or five sessions the engine won't guess for you — it offers the two splits that fit and lets the athlete choose." | **F5** (split resolution) |
| 9 | Choose **Upper / lower** → the plan resolves in place: **Day 1 · Upper**, all sets **3×8–12** unless noted — **Barbell bench press · Incline dumbbell press · Dumbbell flye** (chest), **Barbell overhead press · Dumbbell front raise · Dumbbell lateral raise** (shoulders), **Pull-up · Lat pulldown · Seated cable row** (back), **Barbell curl · Dumbbell hammer curl** (biceps), **Barbell close-grip bench press · Triceps rope pushdown (Cable)** (triceps), **Plank 3×30–45s** (core) — **14 exercises**, then Days 2–4 collapsed | "It becomes an actual plan — which days, which exercises, with sets and reps drawn from a 99-exercise catalog, selected from the equipment set in the profile. Isometric holds get a duration instead of a rep range." | **F5** (generation) |
| 10 | **History** tab → the trend line and the weekly heatmap over past check-ins | "Every check-in is persisted and trended." | **F9** |
| 11 | **Forum** → create a **post** with a **title + body + image**; while it uploads, show the **attachment tray + progress bar** | "The forum: posts with image and video attachments, uploaded before publish so nothing half-posts." | Forum #1 |
| 12 | Add a **comment**, and **attach an image to the comment** | "Comments carry media too, not just posts." | Forum #2 |
| 13 | **Like/dislike** the post and the comment; show the **per-item 👍/👎 counts** on the row, the detail and the comment | "Like and dislike on both, with the counts on each." | Forum #3 |
| 14 | Toggle **anonymous** on a post | "Posts can be anonymous — a bonus we kept." | Forum bonus |
| 15 | On your **own post**: **edit** it (the body changes in place), then **delete** a second one you made → it leaves the feed. Open the same menu on **someone else's** post — the options aren't there. ⚠️ **Posts only** — comments have no edit or delete control, so don't reach for one | "You can edit and delete your own posts — and only your own." | Forum #8 (edit/delete-own) |
| 16 | **Chat** → search a user → send a DM with **text + image** → (2nd account) it **arrives with no refresh** + a **notification** | "Direct messages with media, delivered in real time — no refresh — and a notification fires." | Forum #4, #5, real-time |
| 17 | Send a **second DM with an image and no text** → the notification reads **"sent you an attachment"**, not "sent you a message" | "A photo-only message says so, instead of sending the recipient looking for words nobody wrote." | Forum #5 |
| 18 | Back on account 1: a **notification** that account 2 liked your post | "Notifications for votes too." | Forum #5 |
| 19 | **Profile & account** → the **Community engagement** card: upvotes · downvotes · net score received | "And each member can see the engagement their own posts and comments earned." | Forum (engagement) |
| 20 | Same screen, scroll to the account controls: **change display name**, **change password**, **export my data** (a JSON download), **delete account** (show the confirm, then cancel — don't actually delete the demo account mid-take) | "The account is the athlete's: rename it, re-secure it, export everything it holds, or delete it — and deleting takes the uploaded media with it." | Security / data ownership |
| 21 | Try to **upload an oversized file** → rejected; (optional) rapid-fire posts → rate-limited | "Anti-abuse: file-size caps and anti-spam rate-limits." | Forum #6 |
| 22 | Mention the feed came **pre-seeded** — prod already holds real content, so this needs no setup | "The forum launches cold-seeded with clients and history." | Forum #7 |
| 23 | **Add to Home Screen** on a phone (or the installed PWA icon + splash) | "It installs as a phone app — its own icon and splash." | Build polish (PWA) |
| 24 | Cut to **GitHub Actions**: a green run — `checks` → `cross-container stack (test-runner)` → **`e2e (browser · desktop + mobile)`** → `build & push image (GHCR)` → `deploy to Azure VM` | "Every push runs the full suite, the cross-container stack **and** a real browser at two viewports; on green it auto-deploys." | CI/CD (+10) |
| 25 | Show the **job queue**. ⚠️ **Not from the browser** — `/queue/stats` lives on the `ai` container, which has no `ports:` and is deliberately unreachable from outside (only `web` is exposed; that isolation is itself a graded requirement). Film **one** of: a terminal running `docker compose exec ai curl -s localhost:5000/queue/stats` on the VM, or the measured numbers in `docs/DEMO_RUNBOOK.md` | "A bounded queue and a process pool work many predictions in parallel — measured 2.86× throughput at four workers. Only `web` is exposed, so this is read from inside the network." | Job Queue (+5), scaling, isolation |
| 26 | Close on the live URL | "Work Smarter, Not Harder — live, tested, and deployed." | wrap |

## Coverage checklist (tick before you publish)

Every graded feature in `docs/REPORT.md` §2 must appear. Shots 3, 4, 7, 8 and 9 exist because **F2, F5 and F6
were missing from the previous version of this script** — do not drop them to save time.

- [ ] **F1** Accounts / auth — shots 1, 2
- [ ] **F2** Athlete profile — shot 3
- [ ] **F3** Readiness, web path + model — shots 5, 6
- [ ] **F4** Calorie recommendation — shot 6
- [ ] **F5** Workout generator — shot 8 (the split **picker**) then shot 9 (the **resolved plan**), in that order
- [ ] **F6** Program balance — shot 4 (the input) **and** shot 7 (the recommendations it produces)
- [ ] **F7** Action plan / recommendations — shot 7
- [ ] **F8** Dashboard — shot 6
- [ ] **F9** History — shot 10
- [ ] **+5 Job Queue** — shot 25
- [ ] **+10 Forum** — shots 11–22, one per sub-feature the ROADMAP lists: posts (11) · **comment media** (12) ·
      votes with per-item counts (13) · anonymity bonus (14) · **edit/delete-own** (15) · DMs + real-time (16) ·
      notifications incl. the **attachment-only** wording (17, 18) · engagement metric (19) · anti-abuse (21) ·
      cold-seeding (22)
- [ ] **+10 Azure / CI-CD** — shot 0 (live HTTPS) + shot 24 (test-on-commit → auto-deploy)
- [ ] **Security / data ownership** — email-verify (1), 2FA (2), account controls incl. export + delete (20),
      file-size/rate-limit (21), HTTPS (0)

## Filming the F6 shots so the payoff actually lands

Shots 4 and 7 are a pair, and shot 7 only works if shot 4 sets it up. The balance analysis fires only when
weekly volume falls **outside** the guidelines — **over 20** sets for a muscle group, **under 6** (but above
zero), or a **chest-to-back ratio outside 0.67–1.5**. A balanced programme produces **no** recommendations and
the shot falls flat.

The exact numbers in shot 4 were chosen by running the analyser, not by eye. Measured:

| Programme entered | Balance lines produced |
|---|---:|
| Chest 20 · Back 6 | **1** — only the ratio line (20 is not *over* 20; 6 is not *under* 6) |
| Chest 24 · Back 4 | **3** |
| **Chest 24 · Back 4 · Calves 2** | **4** ← use this |

The recommendation list is capped at **5 items total** and the balance lines share it with the readiness
advice, so **not all four reach the screen**. Filmed on the live app with the programme above, the card showed
five lines, **two of them from the programme**, interleaved:

> · Sleep was below target; keep today's effort controlled.
> · **Weekly chest volume is high; consider reducing sets or spreading them across sessions.**
> · Training load is elevated; keep progression conservative and monitor recovery.
> · **Pressing volume is much higher than pulling volume; add back work or reduce chest volume.**
> · Recovery is the priority today; use rest or a light recovery session.

Two is enough for the point, and the interleaving is worth narrating — it shows one engine weighing recovery
and programme together, not two features bolted side by side. Don't promise "four" in the voiceover.

## Beauty pass (class-vote differentiator)

The design pass is shipped and live, so let the visuals sell it in passing — no extra shots, just don't rush:

- **Shot 6:** linger a beat on the **readiness ring** — the 0–100 score **counts up** as the ring fills
  (Whoop/Oura style). It's the signature moment; let it land.
- **Shots 11–15:** the **generative avatars** (each person a consistent colour) and the WhatsApp-style chat
  (day separators, timestamps, "Seen") read as a real app — worth a slow scroll, not a fast click.
- **Any screen:** a theme-aware installable PWA with restrained motion. One line ("a finished, designed
  product, not a prototype") is enough.

## Production tips

- One take if you can; if not, cut on tab-switches so it still feels continuous.
- Keep the voiceover to the "Say" column — it's timed to roughly 5 min at 24 shots.
- Name the file `VID_<id1>_<id2>_<id3>.mp4` to match the submission convention.
- Shot 23 cannot be filmed in the browser — see its row. Decide terminal-vs-report before you start.
- Shots 3 → 4 → 5 → 7 must be filmed **in that order**: the profile feeds the check-in, and the programme
  feeds the recommendations.

## Still outstanding

- **[ FILL IN ] The video itself** — not recorded. Save the final cut as `VID_<id1>_<id2>_<id3>.mp4`.
