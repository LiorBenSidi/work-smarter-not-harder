# Demo clip — recording checklist

Two clips, don't confuse them:
- **Presentation clip (slide 5 "See It Live"): 30–45 s, tight.** ← this checklist.
- **Submission demo video (`VID_<ids>.mp4`): 3–5 min, full walkthrough** → use the shot-list in `WSNH Demo Video Script.md`.

## ✅ Pre-flight (before you hit record)
- [ ] **Start the VM** and confirm `https://app.worksmarternotharder.dev/health` returns **200** (ask Claude to `az vm start`, or portal → Start). *Record against the LIVE deploy so the URL bar proves it's real.*
- [ ] **Model status:** if Shiri's model is in → the readiness result is real. If not yet → either record the **design/pipeline** framing (don't show a prediction number) or wait for the model. Don't show "always Moderate" as if it's real.
- [ ] **Two accounts ready** (for the DM shot): main account logged in, a 2nd account (`coach_maya` or similar) available in another window/incognito.
- [ ] **Clean browser:** full-screen, no bookmarks bar, no extensions/notifications popping, zoom 100%, light or dark theme decided.
- [ ] **Seed one post** in the forum so it isn't empty on camera.
- [ ] Screen recorder set: **1080p, ~30 fps, no system audio** (narrate live in the room, or add captions), cursor visible.

## 🎬 The 30–45 s shot sequence (tight — one take, no dead air)
1. **(0–5s) It's live.** Show the browser URL `app.worksmarternotharder.dev` + the readiness dashboard. *"This is live on the internet."*
2. **(5–20s) The core loop.** Do a **30-second check-in** (sleep, resting HR, soreness, load) → submit → the **readiness signal** appears (Ready/Moderate/Rest + the confidence breakdown + calorie target). *This is the product in one move.*
3. **(20–35s) The forum, real-time.** Open the forum → post or open a post → switch to the 2nd account → send a **DM with an image** → back on account 1 it **arrives with no refresh** + a **notification pulses**. *Proves the +10 forum + real-time.*
4. **(35–45s) Close on live.** Cut back to the URL / the QR. *"Scan it, it's real."*

Keep it to **one continuous screen capture** if you can — cuts read as "staged." If you must cut, keep each shot ≥2s.

## 🎞️ After recording
- [ ] Trim to **≤45 s**; top-and-tail dead frames.
- [ ] Export **MP4, 1080p**. Name the **submission** video `VID_<id1>_<id2>_<id3>.mp4`.
- [ ] **Add to the deck:** Canva → add slide **5** ("See It Live", after Architecture) → **Uploads** → drag the clip in → set **Play → On click**. (Deck then = 9 slides; trim ~30 s off slides 2/4/7 — see `WSNH Speaker Script (8-slide Canva).md`.)
- [ ] **Have it as the fallback** even if you demo live — if the network hiccups in the room, play the clip. For a 5-min hard cap, pre-recorded is the safe default.

## Common mistakes to avoid
- Recording against `localhost` — the whole point is the **live deployed URL** in shot.
- Audio you can't control in the room — record **silent**, narrate live (or burn in captions).
- A prediction that's the placeholder "Moderate" shown as if real — only show a real result once the model is in.
- Over-length — a 60 s clip eats a fifth of your 5 minutes. **45 s max.**
