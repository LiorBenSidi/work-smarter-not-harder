# Installation — Work Smarter, Not Harder

The whole system runs in **three Docker containers** (`web` · `ai` · `db`). One command starts it.

## Prerequisites
- **Docker Desktop** (macOS/Windows) or **Docker Engine + Compose v2** (Linux) — https://docs.docker.com/get-docker/
- Nothing else: Python, the AI model, and MongoDB all run inside the containers.

## Run
```bash
./install.sh --seed      # or plain ./install.sh to start with an empty database
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

## Populate demo content
A brand-new database starts **empty** (real product behaviour), so do this too — it is what turns the
app from a login screen into a working demo. Either pass `--seed` to the installer above, or run this
**after the stack is up** (in another terminal):
```bash
./seed.sh
```
It creates **15 athletes**, up to **60 days of check-in history each** — scored by the real model, so
the history agrees with the dashboard — a forum of **25 posts and 28 comments** with votes, Hebrew and
English direct-message threads, notifications, and image/video attachments on both posts and DMs.

Idempotent — safe to re-run; it does nothing if the forum already has content. Then log in as a seeded
client (e.g. **`coach_maya`**) with the demo password **`demo-seed-pw`** and browse the forum.

> **If it can't find the seed script:** Docker only shares certain folders with its VM. If the project sits
> outside those (e.g. under `/tmp`), the mount is empty and `./seed.sh` says so and prints the fix — either
> move the project under your **home directory** and re-run, or allow the folder in
> *Docker Desktop → Settings → Resources → File sharing*. Keeping the project in your home directory avoids this entirely.
>
> **On Windows this had a second cause, now fixed in `seed.sh` (#580).** Git Bash rewrites *both* halves
> of a `-v "$PWD:/repo"` argument into Windows paths, so the repo mounted at `C:/repo` and `/repo` was
> empty — from any folder, home directory included. `seed.sh` now sets `MSYS_NO_PATHCONV=1` and
> `MSYS2_ARG_CONV_EXCL='*'` itself; if you run the manual command below by hand in Git Bash, keep them.

Equivalent manual step:
```bash
MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*' \
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
