# WSNH — Canva notes (paste one block per slide)

Canva editing can't set notes via the API, so paste these by hand. In the Canva editor, open each slide → click **Notes** at the bottom of the slide → paste that slide's block. Deck: design `DAHO6FXsV5o`, 8 slides. Hard cap **5:00**, two handoffs (Shiri → Lior → Elad).

---

### Slide 1 — Work Smarter, Not Harder  *(paste ↓)*

SHIRI · 1/8 · ~20s · (opens). Have the live URL / QR tab already open.
"Hi, we're Git Push & Pray — Shiri, Lior and Elad. Our project is Work Smarter, Not Harder, an AI training-readiness coach. It's LIVE right now on Azure — the QR takes you straight to it, try it while we talk."

---

### Slide 2 — Push Today or Recover?  *(paste ↓)*

SHIRI · 2/8 · ~45s.
"Every athlete faces one question each morning: push hard, or recover? Guess wrong and you overtrain or undertrain. Our app answers it in 30 seconds — a check-in on sleep, resting HR, soreness and load — and returns ONE signal: Ready, Moderate, or Rest, plus a recommendation and a calorie target. Not another dashboard. One decision, every morning."

---

### Slide 3 — A Local AI Brain  *(paste ↓)*

SHIRI · 3/8 · ~40s · (last Shiri slide → hand to Lior).
"Behind that signal is a LOCAL Random Forest classifier and a recommendation engine — no external API, nothing phones home. The model is baked into the container image, so it runs fully offline and privately. Features in, readiness state out with a probability and recommendations, plus a Mifflin-St Jeor calorie target."
→ HAND TO LIOR: "Lior will show how it's built."
FALLBACK if the model isn't trained by 16.07: present this as the DESIGN + working pipeline (the /predict seam returns valid shapes today); do NOT claim an accuracy number.

---

### Slide 4 — Architecture Overview  *(paste ↓)*

LIOR · 4/8 · ~40s · (Lior's block begins).
"Three Docker containers: web, ai and db. Only WEB is exposed — the model and database are internal, reached through two fixed contracts: /predict from web to ai, and a small data API from web to db. It runs on an Azure VM, with HTTPS via Caddy and Let's Encrypt. A real, isolated, production-shaped system — not a notebook."

---

### Slide 5 (OPTIONAL — add this slide in Canva) — See It Live  *(paste ↓)*

DEMO · ~30–45s · recommended PRE-RECORDED (safer than live for the 5-min cap).
On-slide: title "See It Live" · subtitle "app.worksmarternotharder.dev".
"Rather than tell you it works — here it is, live: a 30-second morning check-in, the readiness signal, and a post in the forum, all on the deployed app."
CUE: play the clip (VID_318155801_207490913_319000725.mp4), set to play On click.
⚠️ If you add this slide, the blocks below shift down (Forum → 6, Security → 7, Scaling → 8, Commit → 9), and the deck is 9 slides — trim ~30s from slides 2/4/7 to stay under 5:00.

---

### Slide 5 — Online Forum  *(paste ↓)*  — *(becomes slide 6 if you add "See It Live")*

LIOR · 5/8 · ~35s.
"For the +10 Online Forum we built all SEVEN required features: posts and comments with images and video, likes/dislikes, direct messages, notifications, anti-abuse rate-limits, and cold-seeded content. Everything updates in real time — no refresh — and there's an anonymity toggle for the retained bonus."

---

### Slide 6 — Security, Data & Testing  *(paste ↓)*

LIOR · 6/8 · ~35s · (last Lior slide → hand to Elad).
"It's built to be safe: password hashing, two-step login OTP, email verification, CSRF protection and injection-safe queries. And it's TESTED — all five course test types across 715 tests, including a real-Mongo integration suite and a cross-container end-to-end test that both GATE the build. A broken wire path can't reach deploy."
→ HAND TO ELAD: "Elad takes it from performance to production."

---

### Slide 7 — AI Job Queue & Scaling  *(paste ↓)*

ELAD · 7/8 · ~40s · (Elad's block begins).
"Predictions don't run inline — they go onto a BOUNDED queue worked by a PROCESS pool (processes, not threads, because the GIL blocks CPU-bound parallelism). Under overload it sheds with 503 instead of piling up. And it scales on two axes: growing the pool gives 2.86x throughput with p95 halved, and a second AI replica gives another 1.60x. Measured, reproducible numbers."

---

### Slide 8 — Commit to Live  *(paste ↓)*

ELAD · 8/8 · ~45s · (close).
"And it ships itself. Every push runs lint, security scan, tests and the cross-container E2E; on green it builds, deploys to Azure over HTTPS, and a health gate auto-rolls-back if anything's unhealthy. That pipeline put the live URL up. So: a full app, the job queue, the forum, and a live CI/CD deploy — 75 + 5 + 10 + 10, built, tested, running. Scan the QR, try it yourself — and VOTE FOR US."
