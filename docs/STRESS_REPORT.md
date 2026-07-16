# Full-System Stress Report — what falls, what holds

**Date:** 2026-07-16 · **Owner:** Elad · **Scenario:** [`tests/Stress_Tests/locustfile_full_system.py`](../tests/Stress_Tests/locustfile_full_system.py)
**Stack under test:** the 3-container dev stack (`docker compose up --build`, one host: web = gunicorn 2 workers × 4 gthread threads, db = mongo:7, ai = job queue + placeholder model), commit `d2f6d5a` (includes the #313 media limits).

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
| **AI path (`/checkin` → job queue → model)** | Never shed (no 503) at any stage — the queue's backpressure was never reached because web saturates first; ai CPU stayed low (placeholder model; re-measure when Shiri's real model lands). |
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
1. **Raise web concurrency on a bigger host** — workers are hardcoded (`--workers 2` in `web/Dockerfile`, sized for the B1s VM). Making it env-tunable (`GUNICORN_WORKERS`) would let the same image use a larger VM; at ~78 RPS/2-workers, 4 workers projects to roughly ~150 RPS before db becomes the constraint. *(Lior's tier — recommendation only.)*
2. **Rate-limit storage is per-process** (`memory://`, documented in `web/ratelimit.py`) — with more workers the caps loosen N×; point `RATELIMIT_STORAGE_URI` at redis if workers grow.
3. **Forum list pagination** — the one endpoint that visibly leads the latency pack under load.
4. **Re-run this file when the real model lands** — ai never became the bottleneck against the placeholder; the queue's 503 backpressure story should be re-measured with real inference times (`LOCUST_TARGET=ai` in `locustfile.py` covers the direct-at-ai axis).

## 5. Reproduce

```bash
docker compose up --build -d                     # wait for /ready
# optional: register a 'stress_hub' user once (DM recipient); else DMs 404 (tracked as pass)
locust -f tests/Stress_Tests/locustfile_full_system.py --headless \
       -u 100 -r 10 -t 2m --host http://localhost:8000 --csv full_system
# stage -u through 20/50/100/200/300 to reproduce the table; watch `docker stats` alongside.
```

Stress data lands in the dev database only (`st_*`/`fence_*` users, their posts/DMs/media); `docker compose down -v` clears it.
