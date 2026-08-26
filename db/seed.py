"""Seed MongoDB with indexes, validators, and cold-start forum content. OWNER: Lior.

**Cold-seeding (rubric §7):** a brand-new deploy comes up already populated — a few *fake*
clients, with posts **and** comments (and a few likes) on the forum — so the first real
visitor doesn't land in an empty room. It's the last of the Forum's seven sub-features.

Idempotent, safe to run repeatedly:
- users are created only if the handle is absent (``create_user`` is a no-op on an existing handle);
- the forum content is inserted only when the forum is **empty**.

Everything is written through the real ``web/services/db.py`` CRUD, so each seeded row has *exactly*
the same shape as a user-created one (same fields, same indexes, same validators) — no hand-built
documents that could drift from the app's contract. Only ``created_at`` is adjusted afterwards, to lay
the content out over a realistic recent timeline instead of all appearing "just now".

Run against any Mongo reachable from wherever you run this:
    MONGO_URI="mongodb://localhost:27017/worksmarter" python db/seed.py
The project's own ``db`` service is ``expose``-only (no host port), so that form cannot reach the compose
stack — use ``./seed.sh``, which runs this on the compose network. See db/README.md.
"""
import importlib.util
import logging
import os
import shutil
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from werkzeug.security import generate_password_hash

logger = logging.getLogger("seed")

ROOT = Path(__file__).resolve().parent.parent
DB_PY = ROOT / "web" / "services" / "db.py"

DAY = 86_400  # seconds

# Fake clients get a shared, NON-SECRET demo password (these are throwaway seed accounts, never real
# people) so the forum can be browsed / posted-to live during the demo. Override with SEED_USER_PASSWORD.
SEED_PASSWORD = os.environ.get("SEED_USER_PASSWORD", "demo-seed-pw")

CONTENT_PY = ROOT / "db" / "seed_content.py"


def _load_content():
    """Load ``seed_content.py`` by absolute path.

    A plain ``import seed_content`` would work in the container but NOT under the test fixture,
    which loads this file via ``spec_from_file_location`` and so never puts ``db/`` on ``sys.path``.
    Same reason ``_load_db`` exists.
    """
    spec = importlib.util.spec_from_file_location("seed_content", str(CONTENT_PY))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CONTENT = _load_content()

# The data lives in seed_content.py; these names stay here because they are the seed's public
# surface — `test_seed.py`, `test_seed_mongo.py` and any future caller read them from this module.
SEED_USERS = CONTENT.USERS                    # (handle, display_name, email)
SEED_POSTS = CONTENT.SEED_POSTS               # (author, title, body, age_days), OLDEST first
SEED_COMMENTS = CONTENT.SEED_COMMENTS         # (post_index, author, body, age_days)
SEED_POST_VOTES = CONTENT.SEED_POST_VOTES     # (post_index, voter)
SEED_COMMENT_VOTES = CONTENT.SEED_COMMENT_VOTES   # (comment_index, voter)


def _ensure_web_importable():
    """Put the web tier's package root on sys.path.

    ``media_store`` and ``ai_client`` both do ``from services import ...``, and Python puts the
    SCRIPT's directory on sys.path (here ``db/``), never the working directory — so without this the
    imports fail inside the very container that ships those modules.
    """
    web_dir = str(ROOT / "web")
    if web_dir not in sys.path:
        sys.path.insert(0, web_dir)


def _load_ai_client():
    """Load ``web/services/ai_client.py``, or return None when it cannot be imported."""
    try:
        _ensure_web_importable()
        spec = importlib.util.spec_from_file_location(
            "ai_client", str(ROOT / "web" / "services" / "ai_client.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception as exc:                       # noqa: BLE001 - any import problem means "no scorer"
        logger.info("ai client unavailable (%s) — history will use the offline scorer", exc)
        return None


def _media_limits():
    """The upload route's OWN constraints, read from ``web/config.py`` so they cannot drift.

    The seed writes through media_store directly and never passes ``POST /media``, so nothing else
    applies the allowlist or the size cap to seeded bytes. Without this, dropping an unsupported or
    oversize file into ``db/seed_media`` would put a blob on prod that a real upload would have
    rejected with 400/413, and only a human looking at the forum would ever notice.
    """
    fallback = ({"image/png", "image/jpeg", "image/webp", "image/gif", "video/mp4"}, 10 * 1024 * 1024)
    try:
        _ensure_web_importable()
        spec = importlib.util.spec_from_file_location("wsnh_config", str(ROOT / "web" / "config.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        cfg = mod.Config
        allowed = {m.strip() for m in str(cfg.MEDIA_ALLOWED_MIME).split(",") if m.strip()}
        return (allowed or fallback[0]), int(cfg.MEDIA_MAX_BYTES)
    except Exception as exc:                       # noqa: BLE001 - any import problem -> documented defaults
        logger.info("could not read media limits from web/config.py (%s) - using the documented defaults", exc)
        return fallback


def _load_db():
    spec = importlib.util.spec_from_file_location("db", str(DB_PY))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _iso(epoch_seconds):
    """Epoch -> the UTC ISO-8601 string ``add_history`` stores (its YYYY-MM-DD prefix is the day key)."""
    return datetime.fromtimestamp(epoch_seconds, timezone.utc).replace(microsecond=0).isoformat()


def _backdate(coll, doc_id, age_days):
    """Move a just-created row's ``created_at`` back by ``age_days`` (realistic timeline)."""
    coll.update_one({"id": doc_id}, {"$set": {"created_at": time.time() - age_days * DAY}})


def _seed_users(db_mod, db):
    """Create the fake clients (idempotent — an existing handle is skipped). Returns how many were new."""
    password_hash = generate_password_hash(SEED_PASSWORD)
    created = 0
    for handle, display_name, email in SEED_USERS:
        if db_mod.create_user(db, handle, password_hash, email=email, display_name=display_name):
            created += 1
    return created


def _seed_forum(db_mod, db, force=False):
    """Insert posts + comments + likes, ONLY if the forum is empty. Returns ({posts, comments}, post_ids, comment_refs).

    ``force`` skips the empty-forum guard. It exists for ONE job: re-seeding an environment that
    already holds content (the prod box, after test accounts are purged), where the guard would
    otherwise make the run a silent no-op. It is off everywhere else and must stay off — a forced run
    on an already-seeded database duplicates every post, because post ids are random and no unique
    index dedupes them.
    """
    if not force and db.forum_posts.count_documents({}, limit=1) != 0:
        logger.info("forum already has posts — skipping content seed (idempotent)")
        return {"posts": 0, "comments": 0}, [], []
    if force and db.forum_posts.count_documents({}, limit=1) != 0:
        logger.warning("force=True: seeding into a forum that already has posts")

    post_ids = []
    for author, title, body, age in SEED_POSTS:
        post = db_mod.forum_create_post(db, author, title, body, False)
        _backdate(db.forum_posts, post["id"], age)
        post_ids.append(post["id"])

    comment_refs = []
    for post_index, author, body, age in SEED_COMMENTS:
        comment = db_mod.forum_add_comment(db, post_ids[post_index], author, body)
        _backdate(db.forum_comments, comment["id"], age)
        comment_refs.append((post_ids[post_index], comment["id"]))

    for post_index, voter in SEED_POST_VOTES:
        db_mod.forum_vote(db, post_ids[post_index], voter, 1)
    for comment_index, voter in SEED_COMMENT_VOTES:
        post_id, comment_id = comment_refs[comment_index]
        db_mod.forum_vote_comment(db, post_id, comment_id, voter, 1)

    logger.info("seeded %d posts + %d comments (+ likes)", len(SEED_POSTS), len(SEED_COMMENTS))
    return {"posts": len(SEED_POSTS), "comments": len(SEED_COMMENTS)}, post_ids, comment_refs


def _seed_profiles(db_mod, db):
    """Save each athlete's profile. Returns how many were written.

    Profiles are what ``derive_tier`` reads, so this is also what makes the seeded population span
    beginner / intermediate / advanced instead of all looking the same. Written through
    ``save_profile``, so the stored shape is identical to one the profile form produces.
    """
    written = 0
    for handle, profile in CONTENT.PROFILES.items():
        db_mod.save_profile(db, handle, dict(profile))
        written += 1
    return written


def _vary(day, field, lo, hi):
    """A small deterministic wobble in [lo, hi], derived from the day and the field.

    Deterministic on purpose: re-running the seed must reproduce the same history, so a reviewer who
    re-seeds sees the same dashboard, and so nothing here depends on ``random`` (which would make the
    result differ between the local run and the prod run).
    """
    return lo + (day * 7 + field * 13) % (hi - lo + 1)


def _metrics(handle, day_offset):
    """The five check-in numbers for ``handle``, ``day_offset`` days ago.

    Deterministic: re-running the seed reproduces the same history, so a reviewer who re-seeds sees
    the same dashboard, and the local run and the prod run agree. Nothing here uses ``random``.
    """
    shape = CONTENT.HISTORY[handle]
    # readiness drifts across a fortnight rather than jumping, so the trend line reads as a person
    wave = (day_offset % 14) / 14.0
    fatigue = max(1, min(9, shape["base"] + int(round(shape["swing"] * wave)) + _vary(day_offset, 1, -1, 1)))
    soreness = max(1, min(9, fatigue + _vary(day_offset, 2, -2, 1)))
    load = max(1, min(9, 4 + _vary(day_offset, 3, -1, 3)))
    sleep = round(max(4.5, min(9.5, shape["sleep"] - wave * 1.5 + _vary(day_offset, 4, -4, 4) / 10.0)), 1)
    hr = shape["hr"] + int(round(6 * wave)) + _vary(day_offset, 5, -2, 2)
    return {"sleep_hours": sleep, "resting_hr": hr,
            "fatigue": fatigue, "soreness": soreness, "training_load": load}


def _offline_assessment(handle, metrics):
    """Fallback scoring for when ``ai`` is unreachable.

    This is a COARSE stand-in, not a second copy of the model: it cannot reproduce
    ``ai/inference.py::_choose_state``'s trained Ready threshold, so a history scored this way can
    disagree with the live dashboard on the same numbers. The seed says so in its log line when it
    falls back, and the real scorer is preferred precisely so that never happens on a normal run.
    """
    fatigue, soreness = metrics["fatigue"], metrics["soreness"]
    if fatigue >= 7 and soreness >= 6:
        state, proba = "Rest", {"Rest": 0.62, "Moderate": 0.31, "Ready": 0.07}
    elif fatigue >= 5:
        state, proba = "Moderate", {"Moderate": 0.66, "Rest": 0.21, "Ready": 0.13}
    else:
        state, proba = "Ready", {"Ready": 0.78, "Moderate": 0.18, "Rest": 0.04}
    base = CONTENT.CALORIES[handle]
    return {"state": state, "proba": proba,
            "recommendations": CONTENT.RECOMMENDATIONS[state],
            # a Rest day is a lighter day: the live engine trims the target rather than holding it flat
            "calories": base if state != "Rest" else base - 250}


def _entry(handle, day_offset, scored):
    """One check-in row — the exact shape ``add_history`` stores, built from a scoring result."""
    return {
        "timestamp": _iso(time.time() - day_offset * DAY),
        "metrics": _metrics(handle, day_offset),
        "assessment": scored["state"],
        "proba": scored["proba"],
        "calories": scored.get("calories"),
        "recommendations": scored.get("recommendations") or [],
    }


def _seed_history(db_mod, db, ai_url=None):
    """Write each athlete's daily check-in log. Returns (entries_written, scored_by_the_real_model).

    Each row is scored by the REAL model when ``ai`` is reachable, through the same
    ``ai_client.build_features`` -> ``predict`` seam ``/checkin`` and ``/dashboard`` use. That matters
    for more than tidiness: the app decides the displayed state with ``_choose_state``'s trained Ready
    threshold, so anything scored by a local rule of thumb can say "Ready" in the history heatmap
    while the dashboard says "Rest" for the same numbers. Scoring here removes that whole class of
    disagreement — a seeded row is a row the model really produced.

    Falls back to ``_offline_assessment`` the first time ``ai`` does not answer, and stays there for
    the rest of the run rather than retrying 500 more times.

    One row per calendar day (``add_history`` replaces a same-day entry), skipping each athlete's
    ``gaps`` — real people miss days, and a heatmap with no holes looks generated.
    """
    client = _load_ai_client() if ai_url else None
    scored_live = 0
    written = 0

    for handle, shape in CONTENT.HISTORY.items():
        profile = CONTENT.PROFILES.get(handle) or {}
        gaps = set(shape["gaps"])
        for day_offset in range(shape["days"]):
            if day_offset in gaps:
                continue
            metrics = _metrics(handle, day_offset)
            scored = None
            if client is not None:
                features = client.build_features(dict(profile), metrics)
                result = client.predict(ai_url, features)
                if result and result.get("state"):
                    scored = result
                    scored_live += 1
                else:
                    logger.info("ai did not answer — scoring the rest of the history offline")
                    client = None          # one failure is enough; don't retry per row
            db_mod.add_history(db, handle, _entry(handle, day_offset,
                                                  scored or _offline_assessment(handle, metrics)))
            written += 1

    if scored_live:
        logger.info("scored %d/%d check-ins with the real model", scored_live, written)
    else:
        logger.warning("history scored OFFLINE — states may disagree with the live dashboard")
    return written, scored_live


def _seed_messages(db_mod, db):
    """Write the DM threads. Returns (message_count, {(a, b): [message_ids]}).

    The ids come back so media can be bound to the exact message that carries an attachment.
    """
    written = 0
    ids = {}
    for a, b, thread in CONTENT.DM_THREADS:
        for sender, body, age, _media in thread:
            recipient = b if sender == a else a
            msg = db_mod.message_send(db, sender, recipient, body)
            _backdate(db.messages, msg["id"], age)
            ids.setdefault((a, b), []).append(msg["id"])
            written += 1
        # the older half of every thread is already read; the newest exchange is not, so the
        # unread badge a reviewer sees is real rather than either empty or absurd
        for msg_id in ids[(a, b)][:-2]:
            db.messages.update_one({"id": msg_id}, {"$set": {"read": True}})
    return written, ids


def _seed_notifications(db_mod, db, post_ids, comment_refs, dm_ids):
    """Raise the notifications the seeded votes and DMs would have produced. Returns how many.

    DERIVED, never hand-listed: the seed writes through the CRUD layer rather than the routes, so
    nothing raises these on its own — but hand-writing them would mean copying `routes/forum.py` and
    `routes/messages.py`'s exact `(type, ref, text)` triples into a second place, where they would
    drift the first time either route changed. Building them from the content that was actually
    seeded keeps one source of truth.

    Text is name-LESS on purpose ("upvoted your post"), matching `_notify_vote`: the client composes
    "{live actor} {text}" at render, so a later rename re-resolves instead of freezing a stale name.
    """
    written = 0

    def _add(recipient, ntype, actor, ref, text, age):
        nonlocal written
        if not recipient or recipient == actor:      # the app never notifies you about yourself
            return
        note = db_mod.notification_add(db, recipient, ntype, actor, ref, text)
        if note and note.get("id"):
            _backdate(db.notifications, note["id"], age)
        written += 1

    for post_index, voter in SEED_POST_VOTES:
        author, _title, _body, age = SEED_POSTS[post_index]
        _add(author, "vote", voter, post_ids[post_index], "upvoted your post", max(0, age - 1))

    for comment_index, voter in SEED_COMMENT_VOTES:
        post_id, comment_id = comment_refs[comment_index]
        _post_index, author, _body, age = SEED_COMMENTS[comment_index]
        _add(author, "vote", voter, f"{post_id}:{comment_id}", "upvoted your comment", max(0, age - 1))

    for a, b, thread in CONTENT.DM_THREADS:
        for position, (sender, body, age, media_key) in enumerate(thread):
            recipient = b if sender == a else a
            # #408: a media-only DM is not "a message" to a reader who opens the thread and finds a photo
            what = "sent you a message" if body else "sent you an attachment"
            del position, media_key
            _add(recipient, "dm", sender, sender, what, age)

    return written


def _seed_media(media, media_root, post_ids):
    """Copy the attachment bytes onto the media volume and bind each blob to its target.

    OWNERSHIP: the media index is Elad's store (``web/services/media_store.py``), deliberately
    outside ``db.py``'s seam. This writes through its documented contract — ``add`` then ``bind`` —
    and changes none of its code, exactly as a real upload would.

    ``media`` is injected rather than constructed so tests can pass the same ``FakeMedia`` the app's
    own suite uses. Returns how many attachments were bound.
    """
    if media is None or media_root is None:
        logger.info("no media store injected — skipping attachments")
        return 0

    root = Path(media_root)
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        # MEDIA_ROOT defaults to the CONTAINER's volume path (/app/media). db/README documents running
        # this seed straight from a host too, where that path is neither present nor creatable — and an
        # unwritable media directory must cost the attachments only, never the whole seed.
        logger.info("media root %s is not writable (%s) — skipping attachments", root, exc)
        return 0
    bound = 0

    allowed_mime, max_bytes = _media_limits()

    def _attach(key, owner, target_type, target_id, peers=None):
        nonlocal bound
        filename, mime = CONTENT.MEDIA[key]
        source = ROOT / "db" / "seed_media" / filename
        if not source.exists():
            logger.warning("seed media %s is missing — skipping", source)
            return
        # Mirror what POST /media would have enforced. Skipping (not raising) matches the unwritable
        # media-root path above: one bad file costs its attachment, never the whole seed.
        if mime not in allowed_mime:
            logger.warning("seed media %s is %s, which MEDIA_ALLOWED_MIME rejects — skipping", filename, mime)
            return
        size = source.stat().st_size
        if size > max_bytes:
            logger.warning("seed media %s is %d bytes, over the %d-byte MEDIA_MAX_BYTES cap — skipping",
                           filename, size, max_bytes)
            return
        media_id = uuid.uuid4().hex
        # `<media_id><ext>` is media_store's own naming convention (stored_name), mirrored here so
        # the serve route finds the file. Kept in sync by test_seed_media_uses_the_store_naming.
        ext = os.path.splitext(filename)[1]
        shutil.copyfile(source, root / f"{media_id}{ext}")
        media.add(media_id, owner, mime, source.stat().st_size)
        media.bind(media_id, owner, target_type, target_id, peers)
        bound += 1

    posts_by_index = {i: pid for i, pid in enumerate(post_ids)}
    for post_index, key in CONTENT.POST_MEDIA:
        pid = posts_by_index.get(post_index)
        if pid:
            _attach(key, SEED_POSTS[post_index][0], "post", pid)

    # A DM attachment is addressed by CONVERSATION, not by message. routes/media.py's `_dm_key` is
    # `":".join(sorted([a, b]))`, and GET /messages/<peer>/attachments reads it back with that key.
    # Binding to a message id instead leaves the blob bound but UNREACHABLE — the media record exists,
    # the bytes serve, and the thread renders nothing. Shipped that way in #630; found on prod 27 Aug
    # by calling the endpoint rather than counting what was written.
    for a, b, thread in CONTENT.DM_THREADS:
        dm_key = ":".join(sorted([a, b]))
        for sender, _body, _age, key in thread:
            if key:
                _attach(key, sender, "dm", dm_key, peers=[a, b])

    return bound


def apply_seed(db_mod, db, media=None, media_root=None, force=False, ai_url=None):
    """Create the fake clients and everything they have done. Returns a {users, posts, comments} count.

    Split from ``seed`` so it can run against any db handle (a real Mongo, or an in-memory fake in tests).

    The return value stays exactly {users, posts, comments}: it is a published contract that
    ``test_seed.py`` and ``test_seed_mongo.py`` compare by equality, and callers already read it.
    The rest — profiles, history, messages, notifications, attachments — is reported by log line
    instead of widening the dict.

    Profiles/history/messages/notifications follow the forum's own gate: when the forum was already
    populated they are skipped too, so a second run is a no-op rather than a duplicate.
    """
    users = _seed_users(db_mod, db)
    forum, post_ids, comment_refs = _seed_forum(db_mod, db, force=force)

    if not post_ids:
        return {"users": users, **forum}

    profiles = _seed_profiles(db_mod, db)
    history, scored_live = _seed_history(db_mod, db, ai_url=ai_url)
    messages, dm_ids = _seed_messages(db_mod, db)
    notifications = _seed_notifications(db_mod, db, post_ids, comment_refs, dm_ids)
    attachments = _seed_media(media, media_root, post_ids)
    logger.info("seeded %d profiles, %d check-ins (%d model-scored), %d messages, %d notifications, %d attachments",
                profiles, history, scored_live, messages, notifications, attachments)

    return {"users": users, **forum}


def _media_store(mongo_uri):
    """Build the real ``DbMedia`` index, or ``None`` when it cannot be loaded.

    The store is Elad's (``web/services/media_store.py``) and resolves its collection from an app's
    config, so it is handed a shim carrying only the one key it reads. Outside the ``web`` container
    — a unit test, or a bare checkout — ``services`` is not importable and this returns ``None``, so
    the seed still runs and only the attachments are skipped.
    """
    try:
        _ensure_web_importable()
        spec = importlib.util.spec_from_file_location(
            "media_store", str(ROOT / "web" / "services" / "media_store.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as exc:                       # noqa: BLE001 - any import problem means "no media"
        logger.info("media store unavailable (%s) — attachments will be skipped", exc)
        return None

    class _ConfigOnlyApp:
        """The 1-key surface DbMedia touches: ``app.config["MONGO_URI"]``."""
        config = {"MONGO_URI": mongo_uri}

    return mod.DbMedia(_ConfigOnlyApp())


def seed(mongo_uri, force=False):
    """Provision (indexes + validators) and cold-seed the demo population.

    Returns a {users, posts, comments} count; the rest is logged (see ``apply_seed``).
    ``force`` re-seeds a forum that already has content — see ``_seed_forum``.
    """
    from pymongo import MongoClient

    db_mod = _load_db()
    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
    try:
        db = client.get_default_database()
        db_mod.ensure_indexes(db)
        db_mod.ensure_schema(db)
        logger.info("indexes + validators applied")
        result = apply_seed(db_mod, db, media=_media_store(mongo_uri),
                            media_root=os.environ.get("MEDIA_ROOT", "/app/media"), force=force,
                            ai_url=os.environ.get("AI_URL", "http://ai:5000"))
        logger.info("seed complete: %s", result)
        return result
    finally:
        client.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    uri = os.environ.get("MONGO_URI")
    if not uri:
        sys.stderr.write("set MONGO_URI (with a /dbname), e.g. mongodb://localhost:27017/worksmarter\n")
        sys.exit(2)
    # SEED_FORCE=1 is the prod re-seed switch (see _seed_forum); unset everywhere else.
    seed(uri, force=os.environ.get("SEED_FORCE") == "1")
