<!-- Fill this in — detailed PRs are required. Keep main green: CI (lint · security · tests) must pass before merge. No peer approval required — merge your own PR once CI is green. -->

## What & why
<!-- What does this PR change, and why? Link the related issue/feature. -->

## How
<!-- Key implementation notes / decisions worth a reviewer's attention. -->

## Tests (course: 5 types)
Which test types did you add or run for this change?
- [ ] Unit
- [ ] Integration
- [ ] System (end-to-end)
- [ ] Stress (locust)
- [ ] Security
<!-- Paste the `python -m pytest tests/` result, or note why a type is N/A for this change. -->

## Checklist
- [ ] CI is green (lint · security · unit tests)
- [ ] No secrets committed — `.env` stays local, only `.env.example` is tracked
- [ ] Only `web` is exposed; `db` / `ai` stay internal (no host ports)
- [ ] If the AI changed: the trained model is **baked into the image** (no runtime download), sklearn version pinned
- [ ] Input is validated / NoSQL-injection-safe; passwords hashed (werkzeug); protected endpoints auth-gated
- [ ] Docs updated (`docs/`, `README`, `docs/DESIGN.md`) if behavior changed
- [ ] Branch is `feat|fix|test|docs|chore/…` and merges via this PR (never pushed straight to `main`)

## Screenshots / notes
<!-- For UI or behavior changes; otherwise delete. -->
