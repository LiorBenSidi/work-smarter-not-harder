# Final-Project Guidelines — Work Smarter, Not Harder

> **Source:** TA Elad Kalif, `WSNH_Guidelines.pdf`, 8 Jul 2026 — **supersedes [`FEEDBACK.md`](FEEDBACK.md)**
> (Noam's 25 Jun feedback). This is the current source of truth for final-project grading.

**Course:** Software Engineering for ML (Spring 2026) · **Team:** Lior, Shiri, Elad

---

## Grading & Submission Policy
- **Target score (100 pts):** these guidelines are the bar for a perfect score. You do **not** have to complete
  them all.
- **Partial credit:** awarded per feature for partial completion.
- **Penalties:**
  - Each bug found: **−5 points**
  - Each week of delay in submission: **−5 points**
- **Flexibility:** you may swap a feature for a similar one that tests the same concept — but you **must notify the TA**.

---

## Rubric — 100 points

**75 + 5 (Job Queue) + 10 + 10**

### 1. Project Proposal (75 pts)
A working, **localhost** web application that implements your proposed idea — everything mentioned in your
proposal (except the stretch goals). If you want to remove features, tell the TA beforehand.

### 2. Job Queue (+5 pts) — *new*
A **job queue** for the AI container so it handles **many requests at once from many users**, processed **in
parallel**. This is the new parallelization requirement: a queue sits in front of the model so concurrent
`/predict` calls are queued and worked in parallel rather than serialized.

### 3. Online Forum (10 pts)
An integrated online forum / social layer. Seven sub-features:
1. **Posts** — title + body + image + video attachments.
2. **Comments** — body + image + video attachments.
3. **Like / dislike** — on posts and comments, with visible counts and a per-user total in a personal area.
4. **Direct messaging** — private peer-to-peer messages, with media.
5. **Notifications** — for new DMs and for who liked / disliked your content.
6. **Anti-abuse** — anti-spam protection and anti-huge-file-upload protection.
7. **Cold seeding** — launch pre-seeded with fake clients + historical posts/comments.

Plus: **real-time / no manual refresh** (feeds, chat, notifications), **retrievable chat history**, and a solid
**security posture**.

> The team also built an **anonymity toggle** on posts. The new doc does not list it as a requirement, so it is
> a **retained bonus**.

### 4. Website Deployment & CI/CD (10 pts)
- **Deployment** — deploy the website to an **Azure** cloud server (server + domain supplied on request; you
  implement the deployment). Public and **scalable via parallelization**.
- **CI/CD pipeline** — runs the test set on **each commit**; on green, **auto-deploys** the new version.
- **Partial credit (5 pts):** CI/CD only — tests on each commit **without** deployment.
