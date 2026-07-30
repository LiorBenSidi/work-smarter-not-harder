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
> An unbounded backlog under a flood fails twice: memory grows without limit, and the pool keeps scoring jobs
> whose callers **already timed out** — work for clients that left. Bounded, it **sheds a 503**, which `web`
> already treats as "ai unavailable" and degrades. Load-shedding beats falling over — and a bigger VM only
> moves the memory cliff, it never makes the queue bounded.

**4. Why exactly *one* gunicorn worker on `ai`?**
> The job store is **in-memory, per process**. Two workers = two stores, so `GET /jobs/<id>` would 404 ~half the
> time. Threads take concurrent requests; the parallelism is the pool.

**4b. What if a pool worker *dies*? Or *hangs*?**
> A dead worker normally leaves a `ProcessPoolExecutor` **permanently broken** — every later submit raises. The
> queue **self-heals**: it replaces the pool (generation-guarded — N simultaneous detections rebuild once),
> retries the submit, and the one lost caller gets a retryable 503, never a 500-forever. A *hung* worker is
> **reaped** on a hard wall-clock deadline so its slot returns to the queue; a fully-hung pool is replaced.
> Both defences are **mutation-tested** — we disabled each fix and watched the tests go red.

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
> Unit (279) · Integration (325) · System (13) · Stress (12) · Security (91) = **720** — but the count is not the point: each is guard- and **mutation-tested** (disable the check → the test goes red), not scaffolding. They run on every push;
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
> All **seven** sub-features: posts + comments with image/video · like/dislike with counts **+ a per-user
> received-vote total in the profile's "Community engagement" card** (`GET /me/engagement`, #210 — counts
> only, voter identities never leave the store) · direct messages (P2P + media) · notifications (DMs + who
> liked you) · anti-abuse (rate-limits + file-size caps) · cold-seeding. Everything **real-time** over SSE
> (no refresh), retrievable chat history, plus an **anonymity toggle** as a retained bonus.

**14. Is `/predict` safe under `--scale ai=2`?**
> Yes — `POST /predict` is replica-safe, and it's all `web` calls. `GET /jobs/<id>` is *not* (per-container
> store), so we deliberately don't wire `web` to it — documented and guard-tested.

**15. What's your data model?**
> Mongo collections: `users`, `profiles`, `analysis_history`, `forum_posts`, `messages`, `notifications`,
> `media` — indexed, with `$jsonSchema` validators. `web → db` goes through the `db.py` functions, never raw.

---

### Curveballs (be ready)
- *"What would you do differently?"* → an external job store (redis) to make `/jobs` replica-safe — we chose
  not to add a 4th moving part for an endpoint nothing calls (only `web` calls `/predict`, which *is*
  replica-safe); documented in the risk assessment's "what we deliberately did not mitigate".
- *"What's the weakest part?"* → honest: the model is the last piece; and it's a **single VM** (4 vCPU /
  32 GiB) — one machine, no failover (documented in the risk assessment).
- *"Who did what?"* → Shiri: AI model + recommendations + cold-seed. Lior: web app + data layer + auth/security +
  forum real-time (DM/notifications) + logging + containers + CI/CD. Elad: live deploy + job queue + scaling +
  forum media + stress tests.
