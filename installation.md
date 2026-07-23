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

## Populate demo content (optional)
A brand-new database starts **empty** (real product behaviour). To see a populated app — a few demo
clients plus a forum with posts, comments and likes — run this **after the stack is up** (in another terminal):
```bash
./seed.sh
```
Idempotent — safe to re-run; it does nothing if the forum already has content. Then log in as a seeded
client (e.g. **`coach_maya`**) with the demo password **`demo-seed-pw`** and browse the forum.

> **If it can't find the seed script:** Docker only shares certain folders with its VM. If the project sits
> outside those (e.g. under `/tmp`), the mount is empty and `./seed.sh` says so and prints the fix — either
> move the project under your **home directory** and re-run, or allow the folder in
> *Docker Desktop → Settings → Resources → File sharing*. Keeping the project in your home directory avoids this entirely.

Equivalent manual step:
```bash
docker compose run --rm -v "$PWD:/repo" -e MONGO_URI=mongodb://db:27017/worksmarter web python /repo/db/seed.py
```

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
