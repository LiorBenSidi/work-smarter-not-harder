# PLAN — Lior's open issues + full-feature stress run (2026-07-16)

> Local working plan (NOT committed). Owner: Elad.

## Open issues triage
| # | Title | Lane | Action |
|---|-------|------|--------|
| #313 | Media upload: rate limit + disk cap | **Elad (media)** | **Fix now** (concrete ask) |
| #297 | Media volume base↔prod drift — fixed #294/#295 | Elad (validate only) | Validate + comment + close |
| #276 | AI model backlog | Shiri | Leave — not my lane |

## 1. #313 — `POST /media` rate limit + disk-usage cap
Branch: `fix/media-upload-limits` (off fresh `main`).

TDD order (Red → Green):
1. **Tests first**
   - `tests/Security_Tests/test_rate_limit.py`: media-upload flood → 429 (mirrors forum flood tests; new `rate_limited_media_client` fixture in `conftest.py`).
   - `tests/Integration_Tests/test_media.py`: with a tiny `MEDIA_MAX_TOTAL_BYTES`, uploads past the cap → **507** (JSON error); under-cap upload still 201.
2. **Code**
   - `web/config.py`: `MEDIA_MAX_TOTAL_BYTES` (default 500 MB, env-overridable).
   - `web/routes/media.py`: `@limiter.limit("20 per minute")` on `upload()` (issue's suggested cap, mirrors forum caps) + disk-usage check (sum of files in `MEDIA_ROOT` + incoming `Content-Length` > cap → 507 before write).
   - `.env.example`: document the new var (if media vars listed there).
3. Local gate (ruff+bandit+pytest) → PR → CI green → self-merge → close #313 with a comment.

Skipped (documented in PR): retention/cleanup job — optional per issue, backlog.

## 2. #297 — validate from my end
- Read `docker-compose.yml` + `docker-compose.prod.yml` → confirm `media-data:/app/media` mount+declaration in both.
- Run `tests/Integration_Tests/test_deploy_contract.py` locally (incl. the #295 prod assertion).
- Confirm: volume approach == intended (it is — no object store planned; the live test documents it).
- Comment findings on #297 + close.

## 3. Stress — all committed features, detailed report
Goal (user ask): "what falls and what holds" under many users/requests, across the features we committed to.

1. Stack up: `docker compose up --build -d`, wait `/ready`.
2. Baseline suite: `E2E_BASE_URL=http://localhost:8000 python -m pytest tests/Stress_Tests` (locust burst).
3. Extended multi-feature locust run (headless, staged user ramps — e.g. 20 → 50 → 100 → 200 users) covering:
   auth (register/login), check-in → AI predict (queue), dashboard, history, forum (posts/comments/votes),
   DMs + notifications polling, media upload/serve, static SPA.
4. Watch: p50/p95/p99 latency, failure %, 429s (rate limits — *expected* fences), 503s (AI queue full),
   container CPU/mem (`docker stats`), web worker saturation.
5. Deliverable: `STRESS_REPORT_2026-07-16.md` — per-feature holds/falls table, break points, expected-fence
   vs real-failure split, recommendations.

## Order
#313 (in-lane fix, CI round-trip runs while doing the rest) → #297 validation → stress run + report.
