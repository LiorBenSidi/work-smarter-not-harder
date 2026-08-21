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
| `seed-for-screenshots.py` | fills the two gaps `db/seed.py` leaves — check-in history and a DM thread |
| `capture-screenshot.mjs` | re-takes an app mockup by driving the real UI |
| `build.sh` | renders the PDF, rebuilds the zip, validates the result |
| `metadata.json` | the gallery entry's text |

### Populating the app first

Three tiles need data a fresh account cannot produce: History needs a run of check-ins for its trend
and heatmap, Messages needs a conversation, Forum needs posts. `db/seed.py` covers users and forum
only, so run both:

```sh
./seed.sh                                    # users + forum posts/comments (existing tool)
docker compose run --rm -v "$PWD:/repo" \
  -e MONGO_URI="mongodb://db:27017/worksmarter" \
  --entrypoint sh web -c 'exec python /repo/presentation/showoff/seed-for-screenshots.py'
```

The second prints the demo athlete's credentials; log in as that user to shoot. It writes 49
back-dated check-ins and a five-message thread through the real `db.py` CRUD, so the rows are shaped
exactly like user-created ones.

**Clear E2E debris first** if the suite has run against this database — it leaves posts named
`comment-media-*` authored by `e2e…` handles, which will otherwise end up on the poster:

```sh
docker compose exec -T db mongosh worksmarter --quiet \
  --eval 'db.forum_posts.deleteMany({author:/^e2e/}); db.forum_comments.deleteMany({author:/^e2e/})'
```

### A screenshot went stale

The stack must be running the code you want to shoot. **Rebuild first** — a container left up from
an earlier session serves the old templates, and the screenshot will silently show stale UI:

```sh
REGISTER_VERIFY_EMAIL=0 OTP_ENABLED=0 SMTP_HOST= SESSION_COOKIE_SECURE=0 RATELIMIT_ENABLED=0 \
  docker compose up -d --build
docker compose exec -T web grep -c training-program-group templates/index.html   # sanity: >0
```

Then shoot the screen you need:

```sh
node presentation/showoff/capture-screenshot.mjs presentation/showoff/poster-assets/shot-6-plan.png
node presentation/showoff/capture-screenshot.mjs presentation/showoff/poster-assets/shot-7-profile.png   profile
node presentation/showoff/capture-screenshot.mjs presentation/showoff/poster-assets/shot-8-programme.png programme
```

It registers a throwaway account and fills a profile — including the Advanced-tier weekly programme
(#566) — then either files a check-in and shoots the plan card, or shoots the profile card directly.
All three run at the same mobile viewport as the other tiles. For a screen it does not cover yet, add
a branch next to the `profile` one; the harness API is in
[`tests/E2E_Tests/lib/cdp.mjs`](../../tests/E2E_Tests/lib/cdp.mjs).

**Why `profile` and `programme` are two tiles of one screen.** The profile card is ~2597 CSS px tall,
and a tile prints only its **top ~737** — the poster crops to `aspect-ratio: 741/1400` from the top.
Card-top through programme-bottom spans ~2223 px, so fitting both would take roughly a 0.33× zoom:
about 4px type. Two tiles cost nothing, because at seven the four-column grid left row two holding
three with a gap; the eighth fills it without adding a row or a millimetre of sheet.

The `programme` branch does not pick its scroll offset by eye — it sweeps candidate offsets and keeps
the one that lands the most muscle groups on the **printed** band while keeping the section heading
visible and the equipment chips fully clear of the sticky header. It then prints how many groups
survived the crop, because measuring against the viewport instead of the printed band is exactly how
#566 ended up cropped off the sheet in the first place.

**Which tiles actually go stale:** work out which screens a change touched rather than re-shooting
all eight. `git log <last-shot>..HEAD -- web/ ai/` and then checking the hunk line numbers against
the template is enough — an `ai/` change to exercise selection dates `shot-6-plan`, a profile-form
change dates `shot-7-profile` and `shot-8-programme`, and neither touches the other five.

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

The text names **no counts and no vendors**, on purpose. The exercise catalog grew several times
mid-project and may grow again; naming a number would have dated the poster within a week — and would
have made a routine catalog edit a reason to re-render and re-upload the zip. Same
reasoning retired "Brevo" and "name.com" — the app is provider-agnostic (`SMTP_HOST` is an env var),
so naming whichever provider we happen to use makes the poster wrong the day someone switches.

State capabilities, not implementations or values. Then a feature landing on either plane leaves the
copy true, and only a screenshot needs re-taking — which is what `capture-screenshot.mjs` is for.
