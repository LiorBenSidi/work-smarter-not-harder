# PERSON 2 — Lior — the web application (backend + frontend)

> Your area, the mandatory course items, and a roadmap. How you build it is your call. Your container: `web/` —
> the application **backend** (Flask API, auth, request handling, orchestration) plus the frontend. The only container users reach.

## Your area — this is backend work (and backend is what's graded)
The course grades the **backend**, and `web` is the application backend:
- **API / routes** — `/register` `/login` `/logout` `/profile` `/dashboard` `/history` (the Flask endpoints + their logic).
- **Auth + sessions** — werkzeug hashing, login/session/token handling, the auth-gate decorator, password reset + 2-step login OTP + opt-in remember-this-browser, and the transactional-email service (log backend / real Brevo SMTP).
- **Request handling + validation** — parse and validate input (reject bad types) before it reaches `db`.
- **Orchestration** — call the AI (`ai_client` → `/predict`) and the DB (`db.py`), combine the results, and degrade gracefully when either is down (don't crash).
- **Data layer** (`services/db.py`, `db/seed.py`) — the users/profiles/history/forum CRUD `web` calls, plus the indexes, `$jsonSchema` validators, auth config, backups, and seed.
- **Frontend** — the templates/UI on top; not graded, but it matters for the demo vote.

## Start now — unblocked on day 1
`web` already calls the `ai /predict` stub (which returns the real contract) via `services/ai_client.py`, and reads/writes
data through the `services/db.py` thin-CRUD functions (yours). So you can build the backend (auth, the API routes, the
dashboard) against the in-memory fakes — in parallel, without waiting on the live Mongo container.

**Live email for the team:** the app runs in **mock mode with zero secrets** by default (codes on screen). To
give Elad & Shiri *real* email locally, send them your `.env` over a private channel (AirDrop / DM) → they drop
it in their repo root → `docker compose up --build`. Never commit it (it's gitignored). Server + CI/CD secrets
and the full guide: [`SECRETS.md`](SECRETS.md).

## Your contracts (fixed)
- Call the AI via `services/ai_client.py` → `POST /predict`.
- Read/write data via the `services/db.py` functions (yours — the whole data layer).
- `web` is the only exposed container (host 8000 → 5000).

## Mandatory (course — graded)
- **Password hashing with werkzeug** — never store plaintext.
- **Auth-gate** protected endpoints (logged-out → 401).
- **Validate input** (reject bad types) before calling `db`.
- **Fault tolerance** — AI/DB down → the backend degrades, never crashes.
- **`debug` flag** — `FLASK_DEBUG` is already read in `config.py`; make the app actually honour it (debug mode on when set).
- **Tests run on any machine** — security (wrong pw → 401, gated-without-login → 401, injection rejected) + integration (register → login → dashboard).

## Roadmap — web + data + observability + CI/CD COMPLETE (updated 2026-07-02)
- [x] **Auth (F1)** — `/register` `/login` `/logout` `/me`; werkzeug hashing; session gate (`login_required`); constant-time login (no user-enumeration); injection-safe validation; public `/auth/config` (credential bounds for the UI).
- [x] **Profile (F2)** — `/profile` GET/POST + validation (ranges, bool/type gate).
- [x] **Daily check-in (F3)** — `/checkin`: validate the daily metrics → `ai_client` `/predict` → save the entry to history; fault-tolerant (AI down → saved with no assessment; store down → 503).
- [x] **Dashboard (F7) + History (F8)** — readiness via `ai_client` (degrades when AI down), calories, `/history`.
- [x] **Frontend** — single-page UI + CSRF (double-submit) + responsive theming + a11y (focus, labels, aria-live) + credential tooltips driven by `/auth/config`; **a distinctive "performance-lab" visual identity** (readiness-verdict signature, teal/coral palette, monospace data).
- [x] **Forum** — UI + post/comment/up-down-vote CRUD (anonymity, XSS-escaped) + **edit/delete your own post (author-only)**.
- [x] **Direct messages + live DM notifications** (the Chat tab — PRs #99/#101) — private P2P messaging (a thread is the `{sender, recipient}` pair; auth-gated; XSS-escaped; a caller can only ever address a thread they're in), a conversations list + thread view with **generative per-username avatars**, an **anti-spam messaging rate-limit** (20/min → 429), and **live DM notifications** via a polling feed + a breathing "pulse" on the tab. Real-time via **Server-Sent Events** push (`GET /events` streams `text/event-stream`; the browser holds one `EventSource` open and the server pushes a "notify" ping on each new notification, so the client refreshes with no polling — a slow poll remains only as a fallback); the data seams (`message_*` / `notification_*`) live in `services/db.py`. *(Remaining §10 items — media attachments + file-size, a received-engagement metric, fuller cold-seeding — are open; see [`docs/FEEDBACK.md`](docs/FEEDBACK.md) §2 and [`COLLABORATORS.md`](COLLABORATORS.md).)*
- [x] **Vote notifications** (§2.6) — an up/downvote on your post pushes a live notification to the author through the same notification feed (best-effort — a notify failure never fails the vote; self-votes skipped; rapid re-votes coalesced within a 60s window = anti-spam §2.7). Surfaced in a new Chat **Activity** feed (a vote has no thread to open) with mark-all-read; 9 integration tests + mutation-tested + adversarially reviewed.
- [x] **Comment up/down-votes** (§2.4) — every comment carries its own id + vote tally, so it can be up/downvoted independently of its post; a comment vote pings the **comment** author via the shared feed (the coalesce key is scoped to the comment, so it never collides with the post's). Per-comment ▲/score/▼ controls in the post view; the raw vote tally never leaves the store. 13 tests (3 db-unit + 10 integration) + mutation-tested + live 2-user verified.
- [x] **Thin core data-layer CRUD** (`services/db.py`) — users/profiles/history/forum fns + thread-safe `get_db` + `ensure_indexes` (unique constraints) + votes stored as a list (no username-keyed Mongo fields). **Concurrency-hardened** (atomic create-user dedupe, optimistic-concurrency vote, TOCTOU-safe edit/delete) + malformed-doc guards. In-memory fake for unit tests; a real-Mongo integration suite runs when a DB is up.
- [x] **Week-9 logging** — `logging_config.py` (console + rotating file, `ENABLE_LOGGING`/`LOG_LEVEL`, per-request access log with timing) wired at the gunicorn entrypoint (`wsgi.py`).
- [x] **Container build/run** — `web` (+ `ai`) Dockerfile + the runnable 3-container compose; fault-tolerance hardening on the shared compose (restart policies, healthcheck `start_period`, `web` boots and degrades even if `ai` is down).
- [x] **CI gate** — `.github/workflows/ci.yml` (ruff → bandit → pytest) on every PR + branch-protected `main` + a local pre-commit hook.
- [x] **CI/CD deploy pipeline** (PR #91) — the `build` job (docker build `web`+`ai` → GHCR `latest`+`<short-sha>`, `GITHUB_TOKEN` auth) + the `deploy` job (SSH → Azure VM → `docker compose -f docker-compose.prod.yml pull && up -d` → health-curl on the HTTPS FQDN) + `docker-compose.prod.yml` (VM pulls the SHA-pinned images, never builds) + a `Caddyfile` (auto Let's-Encrypt TLS, HTTP→HTTPS). Gated `push && main && vars.SSH_HOST != ''` so `build` runs now and `deploy` stays dormant until the VM exists. **The live half is Elad's:** provision the VM + its GitHub secrets, make the GHCR packages public, set up UptimeRobot, and run the deploy demo (the +10 is graded on that live demo).
- [x] **Mongo internals** — `ensure_indexes` (unique `users.username`/`forum_posts.id`/`profiles.username` + a `analysis_history.username` perf index), `ensure_schema` (`$jsonSchema` validators on all four collections — DB-layer defense), env-gated container **auth config** (compose + `.env.example`), and `db/seed.py` (idempotent cold-start seeding mechanism). *(The cold-seed content is Shiri's.)*
- [x] **Auth upgrade** (#86/#87/#90) — forgot-password + email-on-registration, **2-step login OTP** + opt-in **remember-this-browser** (OTP hashed at rest + TTL + attempt-lockout; gated off under `TESTING`), and `services/email.py` (log backend by default / real **Brevo** SMTP when configured; signed single-use `itsdangerous` reset tokens). Real inbox delivery verified from the authenticated `worksmarternotharder.dev` domain.
- [x] **Recovery/breathing frontend + installable PWA** (#84/#89) — the mobile-app shell (bottom tab nav · Today/History/Forum/Chat/Profile · readiness confidence bars · history sparkline), an aurora recovery identity, and an installable PWA (manifest + root-scope service worker); live-verified desktop + mobile, dark + light.
- [x] **Optimization (course L7)** (#88) — gunicorn `gthread` workers + stdlib **gzip** (shell 40 KB → 11 KB) + static caching/ETag; measured before/after.
- [x] **Data layer in CI + backups** (#77/#78/#79) — the real-Mongo integration suite runs in CI (a `mongo:7` service), a **system E2E** test (`tests/System_Tests/test_e2e.py`, over HTTP against a live stack), and a **Mongo backup + retention** script (`db/backup.sh`).
- [x] **CI/CD hardening + custom domain + demo** (#91/#92) — **auto-rollback** on a failed deploy (R8.2), a `/ready` readiness gate (DB-ping) that the post-deploy check + external monitor target, a deploy **concurrency guard** + BuildKit **build cache**, **custom-domain** support (`SITE_ADDRESS`, decoupled from the SSH host), real **Brevo** email injected into the deploy, and the [`docs/DEPLOY_DEMO.md`](docs/DEPLOY_DEMO.md) run-sheet (UptimeRobot + acceptance A–I + grader Q&A).
- [x] **Shared final REPORT** (#81) — [`docs/REPORT.md`](docs/REPORT.md): app overview + the features×tests matrix from the real suite + the risk assessment.
- [x] **Frontend polish + Wolt-informed nav** (#112–#133) — a full mobile-app UI pass: a corner account menu (single Profile entry), a check-in **streak badge** + a "check-in due" **capsule**, History/Forum **filter-sort chips**, illustrated **empty states**, a grouped red **"danger zone"**, and a **compact, permanently-centered bottom nav** with an always-Home floating button (Today folded into the Home button; desktop keeps the logo-home + a top-nav). Backend side: GDPR account-deletion / email-consent / data-export + gated debug tracing. All live-verified desktop + mobile, both themes.
- [x] **DM recipient search-and-pick** (#130) — a guarded `GET /users/search` (prefix-ranked, ≥2 chars, capped at 8, public-fields-only, `re.escape`'d `$regex` with a bounded read, per-worker rate-limit, caller excluded) + an autocomplete combobox on the DM composer.
- [x] **Deep adversarial audit + fixes** (#131) — two independent blind reviewers over the recent web work; the confirmed findings (an unbounded search read, a stale Forum-tab post, a DM-dropdown reset gap) fixed + regression-tested. No CRITICAL.
- [x] **Email sender fix** (#132) — a comma in the `MAIL_FROM` display name ("Work Smarter, Not Harder") had been silently breaking **every** real OTP/reset send (SMTP 501 — smtplib read the name as an address list); the `From` is now properly quoted and the envelope sender is passed explicitly. Real Gmail-inbox delivery re-verified.

All gated/validated, adversarial + **mutation-tested**, independently QA-verified, live-browser-tested (dark/light/mobile). The web + data + observability + CI/CD tiers are feature-complete (**463 tests**, `main` green).

**Done live (Lior):** the full 3-container stack runs end-to-end — `/health`, a real web→ai→db request path (**12/12** interactive E2E), the real-Mongo integration suite (**6/6**, incl. the validators + perf-indexes + seed), and Week-9 logging emitting in the container. **Next:** integrate/regress as Shiri's model and Elad's deploy/real-time land; I keep the web + data tiers green as the pieces connect.

## You own the decisions
Page structure, server-rendered vs JS frontend, session vs token, the API shape — your call. Keep the contracts + mandatory items.
