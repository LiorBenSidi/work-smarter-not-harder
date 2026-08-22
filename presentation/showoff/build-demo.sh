#!/usr/bin/env bash
# Rebuild demo.mp4 — the Show Off gallery clip — from demo.html.
#
#   bash presentation/showoff/build-demo.sh
#
# This is the video's equivalent of build.sh: renders the committed source and re-checks the result
# against the gallery's own rules, so a rebuild cannot quietly produce a file that would be rejected.
#
# NOT the graded submission video. That one is minutes long, carries a voiceover, and is filmed by
# hand from `presentation/WSNH Demo Video Script.md`. This clip is silent and capped at 90s.
#
# Writes demo.mp4 in place. build.sh then re-validates it as part of the zip.

set -euo pipefail
cd "$(dirname "$0")"

FRAMES="${TMPDIR:-/tmp}/wsnh-demo-frames"
OUT="demo.mp4"
FPS=30

command -v node   >/dev/null || { echo "error: node not found"   >&2; exit 1; }
command -v ffmpeg >/dev/null || { echo "error: ffmpeg not found" >&2; exit 1; }

echo "==> rendering slides from demo.html"
# render-demo.mjs prints "<file>\t<seconds>" per slide on stdout, progress on stderr.
MANIFEST="$(node render-demo.mjs "$FRAMES")"
[ -n "$MANIFEST" ] || { echo "error: renderer produced no slides" >&2; exit 1; }

echo "==> encoding one segment per slide"
# Each slide becomes its own clip with an exact -t, then the clips are concatenated.
#
# NOT the concat demuxer's `duration` directive: that idiom needs the last file repeated (the demuxer
# drops a trailing duration otherwise), and the repeat then REPLAYS that slide for the same duration
# again -- measured, a 5s outro ran for 10s and the clip came out 62s against a 57s manifest. Encoding
# per slide makes the total exactly the sum of `data-secs`, which is what demo.html says it is.
LIST="$FRAMES/segments.txt"
: > "$LIST"
n=0
while IFS=$'\t' read -r file secs; do
  [ -n "$file" ] || continue
  n=$((n + 1))
  seg="$FRAMES/seg-$(printf '%02d' "$n").mp4"
  # -nostdin is load-bearing: without it ffmpeg reads the while-loop's stdin and swallows part of the
  # next manifest line, so the following slide's path arrives with its leading "/" missing.
  ffmpeg -nostdin -loglevel error -y -loop 1 -t "$secs" -i "$file" \
    -vf "fps=$FPS,format=yuv420p" -c:v libx264 -preset slow -crf 20 -an "$seg"
  printf "file '%s'\n" "$seg" >> "$LIST"
done <<< "$MANIFEST"

echo "==> concatenating $n segments -> $OUT"
# -an: emit NO audio track at all. The rules require silence, and a silent track still counts as a
# track to some checkers -- absent is unambiguous.
ffmpeg -loglevel error -y -f concat -safe 0 -i "$LIST" \
  -c:v copy -movflags +faststart -an "$OUT"

echo "==> validating against the gallery rules"
dur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$OUT")
wh=$(ffprobe -v error -select_streams v -show_entries stream=width,height -of csv=p=0 "$OUT")
aud=$(ffprobe -v error -select_streams a -show_entries stream=index -of csv=p=0 "$OUT")
size=$(ffprobe -v error -show_entries format=size -of csv=p=0 "$OUT")

ok=0
chk() { if [ "$2" = "1" ]; then echo "    [PASS] $1"; else echo "    [FAIL] $1"; ok=1; fi; }
chk "duration 20-90s — ${dur}s"        "$(awk -v d="$dur" 'BEGIN{print (d>=20 && d<=90) ? 1 : 0}')"
chk "1920x1080 — $wh"                  "$([ "$wh" = "1920,1080" ] && echo 1 || echo 0)"
chk "silent — no audio stream"         "$([ -z "$aud" ] && echo 1 || echo 0)"
chk "size $(( size / 1024 / 1024 )) MB" 1

echo
if [ "$ok" = "0" ]; then
  echo "demo.mp4 rebuilt and valid — now re-run build.sh to refresh the zip."
else
  echo "SOMETHING FAILED — fix before rebuilding the zip." >&2
  exit 1
fi
