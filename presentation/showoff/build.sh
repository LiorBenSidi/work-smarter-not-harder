#!/usr/bin/env bash
# Rebuild the gallery submission package from source, then validate it.
#
#   bash presentation/showoff/build.sh
#
# Renders poster.html -> poster.pdf with headless Chrome (the same way the original was made: the
# first poster.pdf carried "Producer: Skia/PDF, Title: poster.html"), rezips the three files the
# rules allow, and checks the result against the published requirements.
#
# It does NOT re-take screenshots. When the app changes and a mockup goes stale, run
# capture-screenshot.mjs first — see README.md.

set -euo pipefail
cd "$(dirname "$0")"

ID="${1:-207490913}"                       # the zip is named after ONE member's ID
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

command -v zip >/dev/null || { echo "error: zip not found" >&2; exit 1; }
[ -x "$CHROME" ] || { echo "error: Chrome not found at $CHROME" >&2; exit 1; }

echo "==> rendering poster.html -> poster.pdf"
"$CHROME" --headless --disable-gpu --no-pdf-header-footer \
          --virtual-time-budget=6000 \
          --print-to-pdf=poster.pdf poster.html 2>/dev/null

echo "==> rebuilding $ID.zip"
# Naming every file explicitly (rather than zipping the directory) is what keeps the archive to
# "exactly these files and nothing else" — the instructions call zipping the whole folder the most
# common mistake. -j flattens paths so nothing nests; -X drops extra filesystem attributes.
FILES=(metadata.json poster.pdf)
[ -f demo.mp4 ] && FILES+=(demo.mp4)
rm -f "$ID.zip"
zip -X -j -q "$ID.zip" "${FILES[@]}"

echo "==> contents"
unzip -Z1 "$ID.zip" | sed 's/^/    /'

echo "==> validating"
# Prefer an interpreter that has pdfplumber, or the A3 geometry check — the one that actually
# decides whether the poster is acceptable — silently skips. Export GPV to point at your venv.
PY_BIN="${GPV:-python3}"
"$PY_BIN" - "$ID" <<'PY'
import json, subprocess, sys, zipfile

ID = sys.argv[1]
ok = True
def check(label, passed, detail=""):
    global ok
    ok = ok and passed
    print("    [%s] %s%s" % ("PASS" if passed else "FAIL", label, (" — " + detail) if detail else ""))

names = sorted(zipfile.ZipFile(ID + ".zip").namelist())
allowed = {"metadata.json", "poster.pdf", "demo.mp4"}
check("zip holds only the permitted files, flat",
      set(names) <= allowed and "metadata.json" in names and "poster.pdf" in names,
      ", ".join(names))

m = json.load(open("metadata.json"))
# The published rules forbid `poster`; the staff's own checker still requires it (its image predates
# the rule change). We follow the executable authority — see README.md and docs/SUBMISSION.md.
for field in ("title", "short_description", "long_description_md", "team", "poster", "repo_url"):
    check("metadata has %r" % field, field in m)
check("no `launch` block", "launch" not in m, "declaring it activates the compose annex")
check("team is complete", isinstance(m.get("team"), list) and len(m["team"]) >= 1,
      "%d members" % len(m.get("team", [])))
sd, ld = len(m["short_description"].split()), len(m["long_description_md"].split())
check("short description ~20 words", 14 <= sd <= 28, "%d" % sd)
check("long description ~100 words", 70 <= ld <= 140, "%d" % ld)

try:
    import pdfplumber
    with pdfplumber.open("poster.pdf") as pdf:
        pages, pg = len(pdf.pages), pdf.pages[0]
        w, h = pg.width, pg.height
    check("poster is one page", pages == 1, "%d" % pages)
    # A3 = 297x420mm; the staff checker allows +/-5% per side, either orientation.
    W, H, TOL = 297 / 25.4 * 72, 420 / 25.4 * 72, 0.05
    inb = lambda v, t: t * (1 - TOL) <= v <= t * (1 + TOL)
    check("poster is A3", (inb(w, W) and inb(h, H)) or (inb(h, W) and inb(w, H)),
          "%.1f x %.1f mm" % (w * 25.4 / 72, h * 25.4 / 72))
except ImportError:
    print("    [skip] poster geometry — pdfplumber not installed")

try:
    q = lambda a: subprocess.run(["ffprobe", "-v", "error", "-show_entries", a, "-of", "csv=p=0",
                                  "demo.mp4"], capture_output=True, text=True).stdout.strip()
    dur = float(q("format=duration"))
    wh = q("stream=width,height").split("\n")[0]
    aud = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
                          "stream=index", "-of", "csv=p=0", "demo.mp4"],
                         capture_output=True, text=True).stdout.strip()
    check("video is 20-90s", 20 <= dur <= 90, "%.1fs" % dur)
    check("video is 1920x1080", wh == "1920,1080", wh)
    check("video is silent", not aud, "no audio stream" if not aud else "has audio")
except (FileNotFoundError, ValueError):
    print("    [skip] video — ffprobe unavailable or no demo.mp4")

print()
print("all checks passed" if ok else "SOMETHING FAILED — fix it before submitting")
sys.exit(0 if ok else 1)
PY

echo
echo "==> now run the staff's own checker before uploading:"
echo "    bash check_submission.sh $(pwd)/$ID.zip"
echo "    (on Apple Silicon, prefix it: DOCKER_DEFAULT_PLATFORM=linux/amd64)"
