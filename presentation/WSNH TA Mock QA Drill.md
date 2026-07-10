# Work Smarter, Not Harder — mock TA Q&A drill

**How to use:** cover the answers, ask yourself each question out loud, then check. A real TA wants the *how* and
the *why*, not just the *what* — every answer below leads with the point that earns the marks. Ordered
easy → hard. (Companion to `WSNH Speaker Notes and QA.md`.)

---

**1. Walk me through your architecture — the containers, how they talk, and why only one is exposed.**
> Three Docker containers. `web` (Flask: frontend + auth + API) is the **only** one with a host port. It
> orchestrates the other two over two fixed contracts: `POST /predict` to `ai` (`{features}` → `{state, proba,
> recommendations}`), and the `db.py` data-layer functions to `db` (MongoDB). `ai` and `db` are **internal
> only**. That isolation is defense-in-depth — the attack surface is one hardened container; nobody hits Mongo
> or the model directly. In prod, only **Caddy** (HTTPS) is public and reverse-proxies to `web`.
> **One-liner:** *only `web` is exposed, so the whole attack surface is one hardened container.*

**2. Why a job queue on `ai`? Why a *process* pool, not threads?**
> A plain route scores `/predict` **inline**, serializing every request. The queue + a `ProcessPoolExecutor`
> work many predictions **in parallel**. Processes, not threads, because scoring is **CPU-bound** and the GIL
> stops CPU-bound threads from overlapping — we measured it: threads 0.96× (no gain), processes 2.86–3.58×. A
> guard test fails if anyone swaps it back to threads.

**3. Why is the queue *bounded*? What happens when it's full?**
> An unbounded backlog under a flood is an **OOM kill** on the 1 GB VM — that drops *every* in-flight request,
> not just the excess. Bounded, it **sheds a 503**, which `web` already treats as "ai unavailable" and degrades.
> Load-shedding beats falling over.

**4. Why exactly *one* gunicorn worker on `ai`?**
> The job store is **in-memory, per process**. Two workers = two stores, so `GET /jobs/<id>` would 404 ~half the
> time. Threads take concurrent requests; the parallelism is the pool. (Also each worker loads its own copy of
> the model — two would OOM the VM.)

**5. What happens if the `ai` container is down?**
> `web` wraps the call in try/except + a timeout; on failure it returns `None` and the dashboard renders with
> `ai_status: unavailable`. `web` even **boots** if `ai` is down. We prove it by stopping the real `ai`
> container (`test_fault_isolation.py`) — `/health` stays 200, the app degrades, doesn't crash.

**6. You claim it's scalable. Show me — with numbers.**
> Two multiplying axes, both **measured** against a CPU-bound workload (not the microsecond placeholder): the
> pool 1→4 = **2.86×** throughput (p95 halved); `--scale ai=2` = **1.60×**. Replicas are sub-linear because
> Docker's DNS round-robins *connections*, not *work* — stated honestly, not smoothed over.

**7. Where's the security? Walk me through it.**
> Werkzeug password hashing; **2-step login** (password → one-time code); **email verification at signup** (no
> fake/borrowed addresses); CSRF double-submit tokens; **injection-safe** string-typed Mongo queries;
> user-enumeration defenses (identical failure responses + a timing decoy hash); single-use signed reset tokens;
> **only `web` exposed**; secrets from GitHub secrets at deploy time (nothing committed); HTTPS via Let's Encrypt.

**8. How does a bad commit get caught before it reaches production?**
> `build` needs **both** `checks` (ruff + bandit + the full suite, with a real Mongo service) **and**
> `compose-e2e` (the real 3-container stack over HTTP). A broken wire path fails the **PR** — it can't reach the
> registry or the deploy.

**9. How does your rollback work?**
> The deploy job records the **last-good image SHA** before deploying the new one (the exact commit CI built, not
> a moving `:latest`). After `up -d` it health-checks `GET /ready` (which pings Mongo → a pass means the whole
> stack serves). If it fails, it rewrites `IMAGE_TAG` back to the previous SHA and redeploys — the VM returns to
> the last working version. The run still ends **red** so we know; the site self-heals.

**10. What are the five test types, and how many tests?**
> Unit (277) · Integration (323) · System (13) · Stress (11) · Security (91) = **715**. They run on every push;
> real-Mongo + cross-container E2E gate the build.

**11. What's a "guard test"? What's "mutation testing"?**
> A **guard test** locks an invariant that's cheap to break and expensive to discover in prod (only `web`
> exposed, queue stays bounded, pool stays processes). **Mutation testing** = we broke each invariant on
> purpose and confirmed a test went red — a test that can't fail is decoration.

**12. Is the AI model real? How accurate is it?**  *(honest answer)*
> The full pipeline is wired and the `/predict` contract is fixed; the trained Random Forest drops into one seam
> (`ai/inference.py:predict_one`). *[If trained by demo day: give accuracy + the readiness classes. If not: "the
> model is the last piece; here's the pipeline returning a readiness signal end-to-end."]*

**13. Show me the forum meets the requirement.**
> All **seven** sub-features: posts + comments with image/video · like/dislike with counts + a personal total ·
> direct messages (P2P + media) · notifications (DMs + who liked you) · anti-abuse (rate-limits + file-size
> caps) · cold-seeding. Everything **real-time** over SSE (no refresh), retrievable chat history, plus an
> **anonymity toggle** as a retained bonus.

**14. Is `/predict` safe under `--scale ai=2`?**
> Yes — `POST /predict` is replica-safe, and it's all `web` calls. `GET /jobs/<id>` is *not* (per-container
> store), so we deliberately don't wire `web` to it — documented and guard-tested.

**15. What's your data model?**
> Mongo collections: `users`, `profiles`, `analysis_history`, `forum_posts`, `messages`, `notifications`,
> `media` — indexed, with `$jsonSchema` validators. `web → db` goes through the `db.py` functions, never raw.

---

### Curveballs (be ready)
- *"What would you do differently?"* → an external job store to make `/jobs` replica-safe (we chose not to — a
  4th container on a 1 GB VM for an endpoint nothing calls); a bigger VM to run 2 web workers.
- *"What's the weakest part?"* → honest: the model is the last piece; and the VM is a single ~1 GB node, so it's
  one machine, no failover (documented in the risk assessment).
- *"Who did what?"* → Shiri: AI model + recommendations + cold-seed. Lior: web app + data layer + auth/security +
  forum real-time (DM/notifications) + logging + containers + CI/CD. Elad: live deploy + job queue + scaling +
  forum media + stress tests.
