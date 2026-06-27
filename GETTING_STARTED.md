# Getting Started — Work Smarter, Not Harder

Zero → a running app → knowing your part, in ~5 minutes. Less comfortable in the terminal? Follow each step
exactly, and ask in the group chat if anything errors.

## 1. Get the code (NOT inside OneDrive / iCloud — cloud sync corrupts git)
First accept the GitHub invite Lior sent you. Then:
```sh
cd ~                       # any folder OUTSIDE OneDrive/iCloud (your home is fine)
git clone https://github.com/LiorBenSidi/work-smarter-not-harder.git
cd work-smarter-not-harder
```

## 2. Run it — watch all 3 containers come up
(Mac: open **Rancher Desktop** first so Docker is running.)
```sh
cp .env.example .env
docker compose up --build          # ~1 min the first time (downloads + builds)
```
In a browser open **http://localhost:8000/health** → you should see `{"status":"ok","service":"web"}`.
That's the whole stack (web + ai + db) running. Stop it with **Ctrl+C** (or `docker compose down`).

## 3. Turn on the quality gate (one time, per clone)
```sh
sh scripts/setup-hooks.sh
pip install -r requirements-dev.txt     # in a Python venv
```
Now `git commit` auto-checks your code (lint · no-`print` · security) and `git push` runs the tests —
before anything reaches GitHub.

## 4. Find your part
| You | Your file | Your area |
|---|---|---|
| **Shiri** | [`PERSON1.md`](PERSON1.md) | the **AI** — model, `/predict`, recommendation engine, dataset |
| **Lior** | [`PERSON2.md`](PERSON2.md) | the **web app** — auth, profile, dashboard, history, frontend |
| **Elad** | [`PERSON3.md`](PERSON3.md) | **infra + deploy + data** — docker, Mongo container + `db.py`, Azure + CI/CD, Forum real-time |

Your file = your area + the must-do (course) items + a roadmap. **How** you build it is your choice.

## 5. The loop (for every change)
1. `git checkout -b feat/your-thing`
2. **Write the test first.** Your scaffolds are in `tests/` (`tests/README.md` shows which). Remove the `skip`, make it fail, then make it pass.
3. Replace the `501` stub in your file with the real code.
4. `git commit` (gate runs) → `git push` (tests run) → open a PR → CI green → **merge it yourself** (no approval needed).
5. **Commit often** — your GitHub history is graded.

## When you're stuck
- Team guide: [`COLLABORATORS.md`](COLLABORATORS.md) · plan: [`docs/ROADMAP.md`](docs/ROADMAP.md) · design + the contracts: [`docs/DESIGN.md`](docs/DESIGN.md)
- The **contracts** (the seams between us — the `/predict` shape, the DB collections, only-`web`-exposed) live in `docs/DESIGN.md`. Don't change them without telling the team.
- Broke a test you didn't write? Don't comment it out — fix it, or ask the owner.
