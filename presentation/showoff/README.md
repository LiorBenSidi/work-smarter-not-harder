# Gallery submission package

The zip that goes into the **Noam's Poster Submission** Moodle box. Not graded, but submitting it
is required. Rules: `how to submit.pdf` ("Updated on 2026-08-18") — see
[`docs/SUBMISSION.md`](../../docs/SUBMISSION.md) Track B for the full reading, including the two
places where the staff's own checker contradicts it.

```
207490913.zip
├── metadata.json
├── poster.pdf
└── demo.mp4      (optional)
```

**Exactly those files and nothing else.** The instructions name zipping the whole folder as the most
common mistake, so `build.sh` stages into a scratch directory rather than zipping in place.

## Refreshing it after the app changes

The whole point of the files below is that a change to the app costs minutes, not an afternoon. The
first `poster.pdf` was printed from a `poster.html` nobody committed, so when the workout plan
shipped there was no source to edit — it had to be reconstructed from the PDF's own text, palette
and embedded images. Don't recreate that situation: **edit the source and re-render.**

| File | What it is |
|---|---|
| `poster.html` + `poster-assets/` | the poster's **source**. Edit this, never the PDF |
| `capture-screenshot.mjs` | re-takes an app mockup by driving the real UI |
| `build.sh` | renders the PDF, rebuilds the zip, validates the result |
| `metadata.json` | the gallery entry's text |

### A screenshot went stale

```sh
docker compose up -d
node presentation/showoff/capture-screenshot.mjs presentation/showoff/poster-assets/shot-6-plan.png
```

It registers a throwaway account, fills a profile, files a check-in and shoots the plan card at the
same mobile viewport as the other tiles. For a *different* screen, copy it and change the
navigation — the harness API is in [`tests/E2E_Tests/lib/cdp.mjs`](../../tests/E2E_Tests/lib/cdp.mjs).

Tiles are cropped to a shared aspect ratio in CSS, so a shot taken at a different viewport still
lines the grid up instead of stretching its row.

### Rebuild and check

```sh
bash presentation/showoff/build.sh
```

Renders `poster.html` → `poster.pdf` with headless Chrome, rezips, and validates: file list, required
metadata fields, ~20/~100 word descriptions, one-page A3 geometry, and the video's duration,
resolution and silence.

The geometry check needs `pdfplumber`. Without it that check **skips rather than fails**, which is
the one you least want to miss — so point `GPV` at an interpreter that has it:

```sh
GPV="$HOME/.venvs/global-py-venv/bin/python" bash presentation/showoff/build.sh
```

Then run the staff's checker, which is the authority that actually matters:

```sh
bash check_submission.sh presentation/showoff/207490913.zip
```

On an Apple Silicon Mac prefix it with `DOCKER_DEFAULT_PLATFORM=linux/amd64` — the image is
published for `linux/amd64` only and otherwise will not run at all.

## Two deliberate deviations

**`poster` is present, although the PDF forbids it.** `how to submit.pdf` says *"Do not add a
`poster` field"*, but the checker's `REQUIRED_METADATA_FIELDS` still demands it — it also demands
`repo_url`, an 18 August rule, so it matches neither version of the instructions. We follow the
executable authority and asked the staff which is correct.

**No `launch` block.** Declaring one activates the compose annex, and the root `docker-compose.yml`
fails it twice: `volumes:` at both service and top level (rule 1 rejects any entry), and no
`mem_limit`/`cpus` on any service (rule 4). The annex applies only to a live launch, so the field is
omitted and the live site stays reachable through `links`.

## Writing the copy so it survives

The text names **no counts and no vendors**, on purpose. The exercise catalog went 87 → 98
mid-project and is still growing; naming a number would have dated the poster within a week. Same
reasoning retired "Brevo" and "name.com" — the app is provider-agnostic (`SMTP_HOST` is an env var),
so naming whichever provider we happen to use makes the poster wrong the day someone switches.

State capabilities, not implementations or values. Then a feature landing on either plane leaves the
copy true, and only a screenshot needs re-taking — which is what `capture-screenshot.mjs` is for.
