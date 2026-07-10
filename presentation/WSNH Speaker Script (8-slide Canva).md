# WSNH — Speaker Script (8-slide Canva deck)

Matches **`WSNH Presentation (Canva).pptx`** (design `DAHO6FXsV5o`). Hard cap **5:00**. Only **2 handoffs** — each person speaks one contiguous block: **Shiri → Lior → Elad**. Live at **app.worksmarternotharder.dev** (QR on slides 1 & 8).

**Budget:** 1) 20s · 2) 45s · 3) 40s · 4) 40s · 5) 35s · 6) 35s · 7) 40s · 8) 45s = **5:00**.
Rehearse once with a timer. Usual overrun = slides 2, 4, 7 — keep to the one point.

---

## ▶ SHIRI — slides 1–3 (≈105s)

**Slide 1 — Work Smarter, Not Harder (20s).**
> "Hi, we're Git Push & Pray — Shiri, Lior and Elad. Our project is *Work Smarter, Not Harder*, an AI training-readiness coach. It's **live right now** on Azure — the QR on screen takes you straight to it, try it while we talk."

**Slide 2 — Push Today or Recover? (45s).**
> "Every athlete faces one question each morning: push hard, or recover? Guess wrong and you overtrain or undertrain. Our app answers it in **30 seconds** — a quick check-in on sleep, resting heart-rate, soreness and load, and it returns **one** signal: **Ready, Moderate, or Rest** — plus a recommendation and a calorie target. Not another dashboard to read. One decision, every morning."

**Slide 3 — A Local AI Brain (40s).**
> "Behind that signal is a **local Random Forest** classifier and a recommendation engine — **no external API**, nothing phones home. The model is **baked into the container image**, so it runs fully offline and privately. It takes your features and returns a readiness state with a probability and personalized recommendations, plus a Mifflin–St Jeor calorie target."
> **→ Hand to Lior:** "Lior will show how it's all built."

---

## ▶ LIOR — slides 4–6 (≈110s)

**Slide 4 — Architecture Overview (40s).**
> "Three Docker containers: **web, ai, and db**. Only **web** is exposed to the internet — the model and the database are internal, reachable only through two fixed contracts: `/predict` from web to ai, and a small data API from web to db. It runs on an **Azure VM**, with **HTTPS** via Caddy and Let's Encrypt. So it's a real, isolated, production-shaped system — not a notebook."

**Slide 5 — Online Forum (40s → speak 35s).**
> "For the +10 Online Forum we built **all seven** required features: posts and comments with images and video, likes and dislikes, **direct messages**, **notifications**, anti-abuse rate-limits, and cold-seeded content. Everything updates in **real time — no refresh** — and there's an **anonymity toggle** for the retained bonus."

**Slide 6 — Security, Data & Testing (35s).**
> "It's built to be safe: **password hashing**, **two-step login OTP**, email verification, CSRF protection and injection-safe database queries. And it's **tested** — all five course test types across **686 tests**, including a **real-Mongo** integration suite and a **cross-container end-to-end** test that both **gate the build**. A broken wire path literally can't reach deploy."
> **→ Hand to Elad:** "Elad will take it from performance to production."

---

## ▶ ELAD — slides 7–8 (≈85s)

**Slide 7 — AI Job Queue & Scaling (40s).**
> "Predictions don't run inline — they go onto a **bounded queue** worked by a **process pool** (processes, not threads, because the GIL blocks CPU-bound parallelism). Under overload it **sheds with 503** instead of piling up. And it **scales on two axes**: growing the pool gives **2.86×** throughput with p95 latency halved, and adding a second AI replica gives another **1.60×**. These are measured numbers, reproducible from the repo."

**Slide 8 — Commit to Live (45s).**
> "And it ships itself. Every push runs lint, security scan, tests and the cross-container E2E; on green it builds, pushes the image, **deploys to Azure over HTTPS**, and a health gate **auto-rolls-back** if anything's unhealthy. That pipeline is what put the live URL up. So: a full app, the job queue, the forum, and a live CI/CD deploy — **75 + 5 + 10 + 10**, built, tested, and running. **Scan the QR, try it yourself — and vote for us.**"

---

## Optional: the "See It Live" demo slide (add it in Canva as slide 5)

**On the slide:** title **"See It Live"**, subtitle **app.worksmarternotharder.dev**, the demo `.mp4` filling the frame (Play → On click).
**Ready-to-paste note:**
> DEMO · ~30–45s · pre-recorded recommended. "Rather than tell you it works — here it is, live: a 30-second morning check-in, the readiness signal, and a post in the forum, all on the deployed app." CUE: play the clip (`VID_318155801_207490913_319000725.mp4`) on click.

**If you add it:** the deck becomes 9 slides — Forum→6, Security→7, Scaling→8, Commit→9 — and you **trim ~30s from slides 2/4/7** to stay under 5:00.
- **Recommended: pre-recorded 30–45s clip** (deterministic — safe for a 5-min hard cap). Shot-list in `WSNH Demo Video Script.md`.
- If live instead: rehearse the exact click-path to under 30s, keep the recorded clip on the slide as a fallback, and have the app already logged in.

## Delivery reminders
- **Name the next speaker** at each handoff (end of slide 3 → Lior, end of slide 6 → Elad).
- **Open the QR / live URL in a browser tab before you start** — one click, no fumbling.
- **Lead and close on "it's live"** — a running URL beats any slide.
- If Shiri's model isn't fully trained by 16.07: on slide 3 present it as the **design + working pipeline** (the `/predict` seam returns valid shapes today) and **don't claim an accuracy number**.
