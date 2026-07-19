# Installation — Work Smarter, Not Harder

The whole system runs in **three Docker containers** (`web` · `ai` · `db`). One command starts it.

## Prerequisites
- **Docker Desktop** (macOS/Windows) or **Docker Engine + Compose v2** (Linux) — https://docs.docker.com/get-docker/
- Nothing else: Python, the AI model, and MongoDB all run inside the containers.

## Run
```bash
./install.sh
```
The script creates a local `.env` on first run (from `.env.example`, gitignored) and then runs
`docker compose up --build`. Equivalent manual steps:
```bash
cp .env.example .env
docker compose up --build
```

When the stack is up, open **http://localhost:8000**.
- Liveness probe: <http://localhost:8000/health>
- **Register a new account.** With no SMTP configured (the default), one-time codes — login OTP,
  signup verification, password reset — are shown **on screen and in the logs**, so no mailbox is needed.

## Stop
Press `Ctrl-C`, then:
```bash
docker compose down       # add -v to also drop the database volume
```

## Notes
- Only **`web`** publishes a port (host **8000** → container 5000). `ai` and `db` are internal to the
  Docker network — there is no host port for them by design.
- To send real e-mail instead of on-screen codes, set `SMTP_*` + `MAIL_FROM` in `.env` (see `.env.example`).
- Live deployment (HTTPS, on Azure): **https://app.worksmarternotharder.dev**
