# Full-System Stress Report — what falls, what holds

**Date:** 2026-07-16 · **Owner:** Elad · **Scenario:** [`tests/Stress_Tests/locustfile_full_system.py`](../tests/Stress_Tests/locustfile_full_system.py)
**Stack under test (§1 baseline):** the 3-container dev stack (`docker compose up --build`, one host: web = gunicorn 2 workers × 4 gthread threads, db = mongo:7, ai = job queue + placeholder model), commit `d2f6d5a` (includes the #313 media limits). **§6 re-measures on the 1×16 web tier (#330/#332); §7 re-runs the whole scenario on the real Random Forest.**

This complements the existing stress assets rather than repeating them:
- `tests/Stress_Tests/test_load.py` — single-IP burst: the **fences** engage (429/503), never 5xx.
- `tests/Stress_Tests/locustfile.py` — the single-IP **abuse** surface + the ai before/after scaling load.
- `docs/SCALING_REPORT.md` — ai pool/replica scaling, measured.
- **This report** — the missing axis: *N distinct well-behaved users using **every** feature at once* (real 2-step signup → check-in→AI, dashboard, history, forum posts/comments/votes, DMs, notification polling, media upload/serve, engagement). Each simulated user gets a distinct client IP (`X-Forwarded-For`, trusted 1 hop by ProxyFix exactly as behind Caddy), so per-IP rate limits behave as they would for real separate visitors — this measures **capacity**, not the abuse fences.

## 1. Staged results (2 min per stage; 300 = 2.5 min spike)

| Users | Requests | Failures | RPS | p50 | p90 | p95 | p99 | max |
|------:|---------:|---------:|----:|----:|----:|----:|----:|----:|
| 20 | 1,876 | 0 | 15.8 | 9 ms | 50 ms | 71 ms | 230 ms | 2.1 s¹ |
| 50 | 4,750 | 0 | 40.0 | 23 ms | 53 ms | 75 ms | 270 ms | 0.6 s |
| 100 | 9,255 | **0** | **78.0** | 26 ms | 110 ms | 170 ms | 370 ms | 0.6 s |
| 200 | 13,268 | 1² | 74.3 | 1.0 s | 2.5 s | 5.7 s | 11 s | 13.7 s |
| 300 | 8,930 | 56 (0.6 %)³ | 59.8 | 3.0 s | 8.3 s | 8.9 s | 10 s | 12.3 s |

¹ one-off warmup outlier during the first ramp (bcrypt-heavy signups landing together).
² a single `RemoteDisconnected` during the ramp burst; every in-session request succeeded.
³ 4 connection drops during the 30 users/s ramp + a ~40-request **cascade**: a user whose signup was the dropped request never got a session, and the scenario then counted each of their later calls as a 401 failure. Real users would just retry the signup. (The committed scenario now idles such users instead, so future runs count only the true drops.)

**Total: ~38,000 requests across every feature — zero 5xx server errors at every stage.**

## 2. What holds

| Surface | Verdict |
|---|---|
| **Everything, ≤ 100 concurrent users** | Clean: 0 failures, p50 ≤ 26 ms, p95 ≤ 170 ms at ~78 RPS. Comfortably above any class-demo audience. |
| **Correctness under overload** | At 200–300 users the site gets *slow*, never *wrong*: no 5xx in ~22k over-saturated requests. Degradation mode is queueing, which is the design intent (shed/queue, don't crash). |
| **Container stability** | 0 restarts, `healthy` end-to-end. `/health` stayed 200 (no Docker/UptimeRobot restart storm — the exact failure `test_load.py` guards). |
| **AI path (`/checkin` → job queue → model)** | Never shed (no 503) at any stage. Re-measured on the **real** Random Forest (2026-07-19, §7): `/checkin` is now the heaviest write (p95 190 ms @ 100u, 570 ms @ 200u) and `ai` CPU does real work (26–97 %), but web still saturates first so the queue's `max_pending` bound is never reached under full-system load — the shed-503 path engages only on the direct-at-`ai` axis (#326). |
| **Media (#313 fixes, verified live)** | Upload/serve held under mixed load; single-IP flood → **429 after 20/min**, and the disk cap returns a clean **507** when tripped. No 5xx. |
| **Rate-limit fences vs normal use** | Distinct-IP users never hit a 429 — the caps only bite abusers, not legitimate traffic (the `test_normal_*` contract, now shown at 300-user scale). |
| **Single-IP abuse fences (live prod-mode stack)** | `/health` burst all-200 · login flood → 429, no 5xx · `/ready` only 200/503 · forum flood → 429 · media flood → 429. (The `test_load.py` forum case needs a `TESTING=1` stack because prod-mode signup requires email-verify — it passes in CI's `compose-e2e`; verified here manually with a verified user.) |

## 3. What falls (and how)

| Break point | Symptom | Root cause | Severity |
|---|---|---|---|
| **~100→200 users: the throughput ceiling** | RPS plateaus at ~74–78; p50 inflates 26 ms → 1 s, p95 → 5.7 s | **web tier saturation**: 2 gunicorn workers × 4 threads = 8 concurrent request slots; requests queue in the socket backlog. web CPU sustained ~200–320 % (peak 669 %), db up to ~320 %, ai mostly idle. | Medium — users see a slow site, nothing breaks. |
| **~300 users: ramp-burst connection drops** | A few `RemoteDisconnected` during a 30 users/s ramp (signup = the most expensive request: 2×bcrypt + Mongo writes) | listen-backlog overflow while all 8 slots hold slow bcrypt work | Medium — rare (4/8,930), and a browser/user retry succeeds. |
| **Beyond the knee, throughput *regresses*** | 78 → 74 → 60 RPS as users grow | classic over-saturation: cycles burn on connection churn + timeouts instead of useful work | Expected behaviour; capacity planning point, not a bug. |
| **Slowest endpoint under load** | `/forum/posts` list: p50 1.5 s, p95 7 s at 200 users (worst of all endpoints) | heaviest read (full post list + votes), no pagination | Low today; first candidate if the forum grows. |

## 4. Recommendations (capacity, not correctness)
1. ✅ **Raise web concurrency** — **DONE (#330).** The finding turned out sharper than "add workers": on this
   4-vCPU VM *threads*, not workers, are the lever (werkzeug's scrypt releases the GIL, so 1 worker × N threads
   already parallelises across all cores; +workers ≈ 0 gain, measured 3.01×≈3.19× at 4-way). `WEB_WORKERS`/`WEB_THREADS`
   are now env-tunable (same image, bigger host), default **1 worker × 16 threads** (1 worker keeps the `memory://`
   caps exact; 16 = the measured knee). Dev↔prod mirrored + an SSE-starvation guard. Re-measured in §6.
2. ✅ **Rate-limit storage is per-process** (`memory://`, documented in `web/ratelimit.py`) — **CLOSED by a guard,
   not by redis.** The risk was never today's config (the default is 1 worker, so the caps are exact); it was that
   raising `WEB_WORKERS` later would make every advertised cap N× looser *silently* — the login cap the Security
   suite proves at 20/min would really be 80/min at 4 workers, with nothing going red. Adding redis would buy a
   fourth container and a new failure mode to support a knob we have no reason to turn (#330 measured +workers ≈ 0
   gain on this VM — threads already use every core, since scrypt releases the GIL). So the *dependency* is pinned
   instead: `test_deploy_contract.py::test_raising_web_workers_without_shared_limiter_storage_cannot_ship` fails
   any shipped compose that defaults web above one worker without configuring `RATELIMIT_STORAGE_URI`, and names
   the trade in the failure message. `docker-compose.scale.yml` (4 workers, by design) is the documented exception
   and a companion test asserts it can never reach a deploy path. Mutation-checked: raising the prod default to 4
   turns the guard red.
3. ✅ **Forum list pagination** — **DONE (#332):** cursor pagination + a `created_at` index. It was the latency leader; §6 shows `/forum/posts` p95 fell ~9× at 200 users.
4. ✅ **Bound the other unbounded reads (#331)** — the same audit found the pattern elsewhere; the two Elad-lane
   rows are now bounded (`forum_received_engagement` scoped to the user's own content + indexes;
   media `list_for_target` capped per target + a compound index). The hot-path rows (history/DM/inbox/notifications) stay open on Lior's tier.
5. ✅ **Re-run this file on the real model** — **DONE (§7, 2026-07-19).** Re-ran the full-system scenario against the baked-in Random Forest: `ai` now does real work (CPU 26–97 %) and `/checkin` is the heaviest write, but web still saturates first so the queue never sheds under full-system load — 0 feature failures, 0 5xx at every stage. The direct-at-`ai` 503-backpressure story (the queue reaching its `max_pending` bound) is the companion axis, measured separately in #326 / `SCALING_REPORT.md`.

## 5. Reproduce

```bash
docker compose up --build -d                     # wait for /ready
# optional: register a 'stress_hub' user once (DM recipient); else DMs 404 (tracked as pass)
locust -f tests/Stress_Tests/locustfile_full_system.py --headless \
       -u 100 -r 10 -t 2m --host http://localhost:8000 --csv full_system
# stage -u through 20/50/100/200/300 to reproduce the table; watch `docker stats` alongside.
```

Stress data lands in the dev database only (`st_*`/`fence_*` users, their posts/DMs/media); `docker compose down -v` clears it.

## 6. Re-measured on the fixed stack (2026-07-17)

The §1 run motivated three issues (#324 web concurrency, #325 forum pagination, #331 unbounded reads). Lior
landed #330 (1 worker × **16 threads**, env-tunable) and #332 (forum cursor pagination + index); I re-ran the
**same** `locustfile_full_system.py` on the rebuilt stack at the knee stages (100 + 200 users) to confirm the
fixes moved the numbers rather than just the code. Same host, same scenario — only the two merges differ.

| @ 200 users | §1 baseline (2×4, no pagination) | Fixed (1×16 + #332) | Change |
|---|---:|---:|---:|
| Throughput | 74 RPS | **122 RPS** | **+64 %** |
| Latency p50 | 1.0 s | **250 ms** | **4× faster** |
| Latency p95 | 5.7 s | **1.6 s** | **3.6× faster** |
| Latency p99 | 11 s | **2.4 s** | **4.6× faster** |
| `/forum/posts` p95 | **7.0 s** (worst endpoint) | **0.8 s** | **~9× faster** |
| 5xx server errors | 0 | 0 | held |

At 100 users (already clean in §1) the gains are smaller but real: p95 170 ms → **130 ms**, `/forum/posts`
p95 down to 140 ms. The 200-user run logged 24 setup-phase drops (0.16 %) — all `RemoteDisconnected` on the
expensive signup/profile requests during the 20 users/s ramp burst, the same class §1 note ³ describes; **every
in-session feature request succeeded (0.00 % on each feature endpoint), and there were no 5xx**.

**Read-outs:**
- **#324 — threads, not workers, were the lever.** Confirmed under load: the burst suite (`CONCURRENCY=16`)
  hung `/ready` on the old 8-thread dev stack and passes on 16 threads (Lior, #330). scrypt releasing the GIL is
  why adding *workers* did nothing here; +threads bought the throughput. The 1×16 default is the measured knee.
- **#325 — pagination erased the forum bottleneck.** `/forum/posts` went from the clear latency leader (p95 7 s)
  to mid-pack (p95 0.8 s). It no longer leads.
- **New leader: `POST /media`** (p50 1.5 s, p95 2.6 s at 200 users) — disk-write bound, an expected shape for an
  upload endpoint, and already fenced by the #313 rate-limit + disk cap. Not a correctness issue; the next
  capacity candidate if media traffic dominates.

Reproduce: the §5 command at `-u 100`/`-u 200` on a stack built from `main` at or after #330/#332.

## 7. Re-run on the real model (2026-07-19)

§1/§6 ran against the microsecond **placeholder**, so the AI path never did real work and rec #5 asked for a
re-run once the model landed. It has: the real Random Forest is now baked into the `ai` image
(`ai/model/model.pkl`). I re-ran the **same** `locustfile_full_system.py` at the knee stages (100 + 200 users,
2 min each) against a stack built from `main` @ `5769cb7` — **web = 1 worker × 16 threads** (the #330 default,
same as §6), db = `mongo:7`, ai = job queue + **real model**, mock-email signup, one seeded DM hub. Host:
Docker Desktop, 8 logical cores.

| Stage | Requests | Feature failures | Setup drops | RPS | p50 | p95 | p99 | max |
|------:|---------:|-----------------:|------------:|----:|----:|----:|----:|----:|
| 100u | 9,221 | **0** | 1 | 77.5 | 29 ms | 190 ms | 450 ms | 1.5 s¹ |
| 200u | 15,984 | **0** | 36² | 134 | 86 ms | 1.0 s | 2.0 s | 3.0 s |

¹ one-off cold-start outlier: the first `/predict` spawns the pool workers and loads the 5 MB model
(~1.8 s warm-up), then steady state is ~27 ms/score.
² all setup-phase `RemoteDisconnected`/`ConnectionAborted` on the expensive signup/profile requests during
the 20 users/s ramp burst — the same class §1 note ³ / §6 describe; **every in-session feature request
succeeded (0 failures on every feature endpoint), no 5xx, no 429, no 503.**

**Read-outs:**
- **`/checkin` (the cross-container AI hot path) held on the real model** — 100u: p50 82 ms / p95 190 ms;
  200u: p50 110 ms / p95 570 ms / **0 failures**. It is now the heaviest *write* (real inference cost), where
  against the placeholder it sat with the cheap forum writes.
- **`ai` is no longer idle.** Container CPU ran **26–74 %** at 100u and **60–97 %** at 200u (vs "stayed low"
  on the placeholder). But it never approached its 4-core cap — **web saturates first** (CPU bursting to
  708 % on the 200u ramp, ~110–143 % steady), so the queue's `AI_QUEUE_MAX_PENDING` bound is never reached
  and `/checkin` never sheds under full-system load. `ai` RSS held flat (~560 MB, the pool's model copies).
- **The 503-backpressure path does engage — on the direct-at-`ai` axis, where the model is the bottleneck.**
  #326/#376 drove `/jobs` to its bound (246/400 shed with 503) on the real model
  (`SCALING_REPORT.md` → *Re-baselined on the real model*). Under *full-system* load web is the limiter, so
  that bound simply isn't the one that binds. Both are true and complementary: shed fires where the model is
  the bottleneck, not where web is.
- **Latency leader unchanged:** `POST /media` (p95 2.1 s @ 200u) — disk-write bound, already fenced (#313).
  The real model did not change the endpoint ranking.

**Verdict:** the full system holds on the real model exactly as it did on the placeholder — clean through
100 users, slow-not-wrong at 200, zero server errors — and the one thing the placeholder could never show,
that the AI path carries real inference without becoming the full-system bottleneck or shedding, is now
measured rather than assumed.

Reproduce: the §5 command at `-u 100`/`-u 200` on a stack built from `main` at/after #330, with the real-model `ai` image.
