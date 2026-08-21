"""Media metadata store (OWNER: Elad) — the web-owned Forum/DM attachment index.

Attachment BYTES live on a web-mounted volume (``MEDIA_ROOT``); this store keeps only each blob's
metadata + what it is bound to (a post / comment / DM), in a dedicated ``media`` Mongo collection that
this module owns. It is deliberately NOT part of Lior's ``db.py`` data-layer seam, so adding media
never touches a teammate's contract. Tests inject an in-memory ``FakeMedia`` with the same method
contract, so the media routes run without Mongo (the DI seam mirrors every other store).

Contract (mirrored by ``tests/conftest.py``'s ``FakeMedia``):
    add(media_id, owner, mime, size)                         -> record an uploaded, still-unbound blob
    get(media_id)                                            -> record dict or None
    bind(media_id, owner, target_type, target_id, peers)     -> bool (False unless owner == uploader)
    list_for_target(target_type, target_id)                  -> list of bound record dicts
    list_for_owner(owner)                                    -> every record this user uploaded (#507)
    delete_for_owner(owner)                                  -> drop those records; returns the count
    list_for_post(post_id)                                   -> the post's records AND its comments' (#544)
    delete_for_post(post_id)                                 -> drop those records; returns the count
    list_unbound_before(cutoff)                              -> abandoned uploads older than cutoff (#557)
    delete_unbound_before(cutoff)                            -> drop those records; returns the count

A record dict: ``{id, owner, mime, size, target_type, target_id, peers}`` where ``target_type`` is one
of ``"post"``/``"comment"``/``"dm"`` (or None while unbound) and ``peers`` is the 2-participant list a
DM attachment is served to.

Erasure (#507): media used to be the one store that SURVIVED account deletion — the index exposed no
owner-scoped read or delete, so `delete_account` had nothing to call and a deleted user's uploads stayed
both in Mongo and on the volume. ``list_for_owner`` / ``delete_for_owner`` close that, and
``purge_owner`` below is the one call that erases both halves (documents *and* bytes) together.

Content erasure (#544): the same gap existed one level down. Deleting a post erased the post and its
comments and left their blobs both on the volume and — because ``_can_view`` treats any ``post``/
``comment`` target as public forum content without asking whether that post still exists — still served
to every logged-in user. ``list_for_post`` / ``delete_for_post`` / ``purge_post`` close that. They are
scoped INSIDE this store: a comment's target id is ``"<post_id>:<comment_id>"`` (#407), so one post id
finds both halves without the forum data layer (Lior's ``db.py``) having to grow a media-aware call.
"""
import logging
import os
import re
import time

logger = logging.getLogger(__name__)

# Allowlisted MIME -> stored file extension, and the `<media_id><ext>` naming convention. This is the
# single place that convention is written down: ``routes/media.py`` imports it for upload/serve, and
# ``purge_owner`` uses it to find the blob belonging to a record. Keep in sync with the
# MEDIA_ALLOWED_MIME default in config.
EXT = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp",
       "image/gif": ".gif", "video/mp4": ".mp4"}


def stored_name(media_id, mime):
    """The on-disk filename for a blob — the convention shared by upload, serve and purge."""
    return media_id + EXT.get(mime, "")


def purge_owner(store, media_root, owner):
    """Erase every blob ``owner`` uploaded: the index documents AND the files under ``media_root``.

    Returns ``(documents_deleted, files_deleted)``. The records are read BEFORE the documents are
    dropped, because the record is the only thing that knows a blob's mime — and therefore its
    filename. A missing file is not an error: a record whose blob was already lost (rotated volume)
    still has to have its document erased, which is the point of the call.
    """
    records = store.list_for_owner(owner)
    documents = store.delete_for_owner(owner)
    files = 0
    for rec in records:
        path = os.path.join(media_root, stored_name(rec["id"], rec.get("mime")))
        try:
            os.remove(path)
            files += 1
        except FileNotFoundError:
            logger.info("media %s had no file on disk while purging %s", rec["id"], owner)
        except OSError:
            # Never abort the cascade over one undeletable file: the document is already gone, so the
            # blob is unreachable through the app either way. Logged so it can be swept later.
            logger.warning("could not remove media file for %s while purging %s", rec["id"], owner,
                           exc_info=True)
    return documents, files


def purge_post(store, media_root, post_id):
    """Erase every blob bound to ``post_id`` — the post's own and its comments' — documents AND files.

    Returns ``(documents_deleted, files_deleted)``. Same shape and same ordering rationale as
    ``purge_owner``: the records are read BEFORE the documents are dropped, because the record is the
    only thing that knows a blob's mime and therefore its filename.
    """
    records = store.list_for_post(post_id)
    documents = store.delete_for_post(post_id)
    files = 0
    for rec in records:
        path = os.path.join(media_root, stored_name(rec["id"], rec.get("mime")))
        try:
            os.remove(path)
            files += 1
        except FileNotFoundError:
            logger.info("media %s had no file on disk while purging post %s", rec["id"], post_id)
        except OSError:
            # One undeletable file must not abort the rest: its document is already gone, so the blob is
            # unreachable through the app either way. Logged so the volume can be swept later.
            logger.warning("could not remove media file for %s while purging post %s", rec["id"], post_id,
                           exc_info=True)
    return documents, files


def purge_unbound(store, media_root, ttl_seconds):
    """Reclaim uploads that were never attached to anything and are older than ``ttl_seconds`` (#557).

    Since #439 the composer uploads BEFORE it publishes, so every draft someone abandons leaves a blob
    that no post, comment or DM points at — invisible in every UI, and counted against
    ``MEDIA_MAX_TOTAL_BYTES`` forever. Without this, one user who never publishes fills the volume and
    every later upload 507s for everybody, with no way back short of deleting files on the VM by hand.

    Age alone is never the condition: an ATTACHED blob is old by definition (a post from last year still
    shows its photo), so only ``target_type is None`` records are candidates. Returns
    ``(documents_deleted, files_deleted)``.
    """
    cutoff = time.time() - ttl_seconds
    records = store.list_unbound_before(cutoff)
    if not records:
        return 0, 0
    documents = store.delete_unbound_before(cutoff)
    files = 0
    for rec in records:
        path = os.path.join(media_root, stored_name(rec["id"], rec.get("mime")))
        try:
            os.remove(path)
            files += 1
        except FileNotFoundError:
            logger.info("abandoned media %s had no file on disk", rec["id"])
        except OSError:
            logger.warning("could not remove abandoned media file %s", rec["id"], exc_info=True)
    logger.info("reclaimed %d abandoned upload(s), %d file(s)", documents, files)
    return documents, files


class DbMedia:
    """Mongo-backed media index. Lazily resolves the ``media`` collection from the app's MONGO_URI, so
    the web app still boots + serves ``/health`` before Mongo is reachable (same pattern as the db.py
    stores in ``app.py``)."""

    def __init__(self, app):
        self._app = app
        self._indexed = False

    def _collection(self):
        from services import db as db_module
        coll = db_module.get_db(self._app.config["MONGO_URI"])["media"]
        if not self._indexed:
            # #331: back list_for_target with a compound index so listing ONE target's attachments is an
            # index seek, not a scan of the whole (growing) media collection. Idempotent; done once.
            coll.create_index([("target_type", 1), ("target_id", 1), ("created_at", 1)])
            # #507: the same argument for the owner-scoped erasure/export reads — without this, deleting
            # an account scans the whole media collection.
            coll.create_index("owner")
            self._indexed = True
        return coll

    @staticmethod
    def _public(doc):
        return {"id": doc["_id"], "owner": doc["owner"], "mime": doc["mime"], "size": doc["size"],
                "target_type": doc.get("target_type"), "target_id": doc.get("target_id"),
                "peers": doc.get("peers"), "created_at": doc.get("created_at", 0)}

    def add(self, media_id, owner, mime, size):
        self._collection().insert_one({
            "_id": media_id, "owner": owner, "mime": mime, "size": int(size),
            "target_type": None, "target_id": None, "peers": None, "created_at": time.time(),
        })

    def get(self, media_id):
        doc = self._collection().find_one({"_id": media_id})
        return self._public(doc) if doc else None

    def bind(self, media_id, owner, target_type, target_id, peers=None):
        # Owner-scoped update: you can only attach a blob YOU uploaded (matched_count == 0 otherwise).
        res = self._collection().update_one(
            {"_id": media_id, "owner": owner},
            {"$set": {"target_type": target_type, "target_id": target_id,
                      "peers": list(peers) if peers else None}},
        )
        return res.matched_count == 1

    def list_for_owner(self, owner):
        """Every blob this user uploaded, bound or not — the export's media section and the read half
        of erasure (#507). Unbounded on purpose: erasure must not silently leave a tail behind, and one
        user's own uploads are already capped by the per-file, per-target and volume-wide limits."""
        return [self._public(d) for d in self._collection().find({"owner": owner}).sort("created_at", 1)]

    def delete_for_owner(self, owner):
        """Drop every media document belonging to ``owner``; returns how many were removed. Bytes are
        removed by ``purge_owner``, which calls this — see that function for why the order matters."""
        return self._collection().delete_many({"owner": owner}).deleted_count

    def _post_scope(self, post_id):
        """Match the post's own attachments AND every comment attachment under it.

        A comment target id is ``"<post_id>:<comment_id>"``, so the comment half is an ANCHORED prefix
        match. ``re.escape`` keeps a post id built of regex metacharacters from being read as a pattern
        (the ids the app mints are hex, but the value reaches here from the URL), and the anchor lets the
        ``(target_type, target_id)`` index still serve the scan.
        """
        return {"$or": [{"target_type": "post", "target_id": post_id},
                        {"target_type": "comment",
                         "target_id": {"$regex": "^" + re.escape(post_id) + ":"}}]}

    def list_for_post(self, post_id):
        """Every blob a post deletion has to take with it (#544). Unbounded on purpose, exactly as
        ``list_for_owner`` is: an erasure that silently leaves a tail behind is the bug being fixed."""
        return [self._public(d) for d in self._collection().find(self._post_scope(post_id)).sort("created_at", 1)]

    def delete_for_post(self, post_id):
        """Drop those documents; returns how many. Bytes are removed by ``purge_post``, which calls this."""
        return self._collection().delete_many(self._post_scope(post_id)).deleted_count

    def list_unbound_before(self, cutoff):
        """Uploads still bound to nothing, older than ``cutoff`` (a UNIX timestamp) — #557.

        Served by the `(target_type, target_id, created_at)` index on its `target_type` prefix, so the
        read stays cheap however large the collection grows.
        """
        return [self._public(d) for d in
                self._collection().find({"target_type": None, "created_at": {"$lt": cutoff}})]

    def delete_unbound_before(self, cutoff):
        """Drop those documents; returns how many. Bytes are removed by ``purge_unbound``."""
        return self._collection().delete_many(
            {"target_type": None, "created_at": {"$lt": cutoff}}).deleted_count

    def list_for_targets(self, target_type, target_ids):
        """Attachments for MANY targets in ONE query, grouped by target id (#407).

        Exists because the per-comment read was an N+1 at the *browser* layer, not the database one:
        a post page holds up to COMMENT_PAGE_DEFAULT (50) comments, and asking per comment meant 50
        parallel requests against a browser limit of ~6 connections per origin — so every other request
        the page needed, the forum feed included, queued behind them.
        """
        ids = list(target_ids)[:self._app.config.get("MEDIA_MAX_COMMENT_TARGETS", 200)]
        if not ids:
            return {}
        cap = self._app.config.get("MEDIA_MAX_ATTACHMENTS_PER_TARGET", 50) * len(ids)
        docs = (self._collection()
                .find({"target_type": target_type, "target_id": {"$in": ids}})
                .sort("created_at", 1).limit(cap))
        grouped = {}
        for d in docs:
            grouped.setdefault(d.get("target_id"), []).append(self._public(d))
        return grouped

    def list_for_target(self, target_type, target_id):
        # Bounded read (#331): the attach route caps a target at MEDIA_MAX_ATTACHMENTS_PER_TARGET, so a
        # matching .limit() here never drops a legitimately-bound blob — it's a defensive ceiling against
        # any pre-cap data or a race, keeping the read O(cap) rather than O(all attachments on the target).
        cap = self._app.config.get("MEDIA_MAX_ATTACHMENTS_PER_TARGET", 50)
        docs = (self._collection()
                .find({"target_type": target_type, "target_id": target_id})
                .sort("created_at", 1).limit(cap))
        return [self._public(d) for d in docs]
