"""Composer/attachment shell contract — the served SPA still ships the upload surface. OWNER: Elad.

Same honesty rule as `test_frontend.py`: this file never executes a line of the page's JavaScript, so
it cannot prove the composer behaves. What it catches cheaply is the shape regressing — a dropped tray
container, a size pre-check removed, the publish order silently flipping back.

The one thing here that is more than a grep is `test_the_forum_composer_uploads_before_it_creates_the_post`:
it compares POSITIONS inside the handler, so it fails if #439's ordering is ever reversed — which is
exactly the regression that would reintroduce a photo-less post being pushed to every client over SSE.

WHAT PROVES THE BEHAVIOUR: the browser scenarios in tests/E2E_Tests/scenarios.mjs tagged "media" —
they drive a real Chrome, pick real files, and read what the user is actually told.
"""
import pytest


@pytest.fixture
def html(client):
    return client.get("/").get_data(as_text=True)


def _forum_handler(html):
    """The forum submit handler, from its onSubmit to the end of that registration."""
    start = html.index('onSubmit("forum-form"')
    return html[start:html.index('onSubmit("dm-reply-form"')]


def _dm_handler(html):
    start = html.index('onSubmit("dm-reply-form"')
    return html[start:html.index("// Growing compose:")]


# ---- the tray (#471): you can see what you picked, and take it off again ----

def test_both_composers_ship_an_attachment_tray(html):
    """Before #471 the only feedback was "1 file attached" — you could not check what you grabbed on a
    phone's grid of near-identical thumbnails, and re-opening the picker and cancelling leaves the old
    selection intact in every major browser, so there was no way to undo it either."""
    assert 'id="forum-tray"' in html and 'id="dm-tray"' in html
    assert "function makeTray(" in html
    assert 'makeTray("forum-files", "forum-tray"' in html
    assert 'makeTray("dm-files", "dm-tray"' in html


def test_the_tray_owns_its_own_file_array_rather_than_the_picker(html):
    """A FileList is immutable, so per-file removal is impossible while the picker is the source of
    truth. The array IS the fix — if this regresses to reading `picker.files`, remove stops working."""
    tray = html[html.index("function makeTray("):html.index("// ---- Direct messages")]
    assert "tray.files.splice(" in tray                       # a single file can be taken back off
    assert "picker.value = \"\";" in tray                      # ...and re-picking the same file still fires


def test_each_picked_file_gets_a_remove_control(html):
    assert 'class="att-x"' in html and 'aria-label="Remove ' in html


# ---- the size pre-check (#438) ----

def test_the_composer_checks_file_size_before_uploading(html):
    """There was NO `.size` check anywhere in the SPA: `accept=` filters type only, so an oversized file
    uploaded to completion on a slow link and was only then rejected by the server's cap."""
    assert "const MEDIA_MAX_BYTES =" in html
    assert "f.size > MEDIA_MAX_BYTES" in html
    for handler in (_forum_handler(html), _dm_handler(html)):
        assert "hasBlocked()" in handler                      # an over-cap file blocks the send


def test_the_size_cap_is_rendered_from_the_server_config(client):
    """The cap and the visible "up to N MB" copy come from MEDIA_MAX_BYTES, so they cannot drift apart
    the way four hard-coded "10 MB" strings could."""
    body = client.get("/").get_data(as_text=True)
    assert "{{ media_max_bytes }}" not in body and "{{ media_max_label }}" not in body   # actually rendered
    assert "const MEDIA_MAX_BYTES = 10485760;" in body
    assert body.count("up to 10 MB") >= 2


# ---- timeout, progress and cancel (#438) ----

def test_the_uploader_arms_a_stall_timeout_rather_than_a_flat_deadline(html):
    """`uploadMedia` was the ONLY request in the SPA that bypassed the shared api() helper and so had no
    timeout at all — a wedged connection never resolved and left the submit button disabled until a page
    reload. A FLAT timeout would be a bug in the other direction: 10 MB over ~200 kbps legitimately takes
    ~7 minutes. Only silence is a failure, so the clock re-arms on every progress event."""
    um = html[html.index("async function uploadMedia("):html.index("async function uploadAll(")]
    assert "UPLOAD_STALL_MS" in um
    assert "xhr.upload.addEventListener(\"progress\"" in um    # byte progress is what makes a stall detectable
    assert "armStall()" in um and "xhr.abort()" in um


def test_the_upload_reports_progress_between_files(html):
    """`uploadAll` uploaded one file at a time and reported nothing between them — not even "2 of 5",
    though the loop already knew both numbers."""
    ua = html[html.index("async function uploadAll("):html.index("function attachWarning(")]
    assert "onStep(" in ua
    assert "Uploading \" + (index + 1) + \" of \" + total" in html


def test_an_upload_can_be_cancelled(html):
    assert 'class="ghost mini att-cancel"' in html
    assert "tray.cancel" in html


# ---- publish ordering (#439) ----

def test_the_forum_composer_uploads_before_it_creates_the_post(html):
    """#439: the post used to be committed FIRST and the upload spent afterwards, so the post existed
    without its photos for the whole upload — and not only for the author, since creating a post bumps
    the forum revision and SSE pushes it to every connected client at once. A failed upload then left
    the post up permanently with no media.

    Position comparison, not a substring: this is the assertion that fails if the order is flipped back.
    """
    handler = _forum_handler(html)
    upload_at = handler.index("uploadAll(picked")
    create_at = handler.index('api("/forum/posts"')
    assert upload_at < create_at, "the post is created before its media is uploaded (#439 regressed)"


def test_the_dm_composer_uploads_before_it_sends(html):
    handler = _dm_handler(html)
    assert handler.index("uploadAll(picked") < handler.index('api("/messages"')


def test_a_wholly_failed_upload_publishes_nothing(html):
    """The point of uploading first: if every file is refused there must be no post left behind. The
    tray keeps the files so the retry is one tap, rather than forcing a re-pick."""
    handler = _forum_handler(html)
    assert "Nothing was posted" in handler
    assert "Upload cancelled" in handler


# ---- comment attachments (#407, TA Online-Forum sub-requirement #2) ----

def test_the_comment_composer_ships_an_attach_control_and_tray(html):
    """Posts and DMs took media; comments did not, while four documents said they did. The live composer
    was `<textarea> + <button>Comment</button>` with no attach control at all."""
    assert 'id="comment-files"' in html
    assert 'id="comment-tray"' in html
    assert 'makeTray("comment-files", "comment-tray"' in html


def test_the_comment_composer_reuses_the_shared_tray(html):
    """Not a second implementation: the same makeTray/uploadAll the other two composers use, so the three
    behave identically and a fix to one is a fix to all."""
    handler = html[html.index('onSubmit("comment-form"'):html.index("function renderComments(")]
    assert "commentTray.sendable()" in handler
    assert "uploadAll(picked" in handler
    assert "hasBlocked()" in handler


def test_the_comment_composer_uploads_before_it_creates_the_comment(html):
    """Same ordering as #439: a comment must not be published without the media it was written around,
    and a failed upload must not leave a stray comment behind."""
    handler = html[html.index('onSubmit("comment-form"'):html.index("function renderComments(")]
    assert handler.index("uploadAll(picked") < handler.index('/comments", { method: "POST"')


def test_a_comment_binds_its_media_to_the_comment_endpoint(html):
    """The blobs must reach the COMMENT's own target, not the post's — otherwise a comment's photo shows
    up on the post and every comment on that post shares one bucket."""
    handler = html[html.index('onSubmit("comment-form"'):html.index("function renderComments(")]
    assert '"/forum/posts/" + id + "/comments/" + cid + "/attachments"' in handler


def test_each_comment_renders_its_own_attachments(html):
    assert 'class="c-atts"' in html
    assert "function loadCommentAtts(" in html


def test_comment_attachments_are_fetched_once_per_open_not_per_render(html):
    """renderComments() re-runs on every vote, every new comment and every in-place refresh, and a page
    holds up to 50 comments — so fetching per render would fire 50 requests each time anyone voted. Each
    comment is fetched once and later renders paint from the cache."""
    fn = html[html.index("function loadCommentAtts("):html.index("// Load a post's FIRST")]
    assert "commentAtts[c.id]" in fn
    assert "if (cached !== undefined)" in fn                  # a known comment repaints without a request
    assert "commentAtts = {}" in html                         # ...and the cache resets with the accumulators
