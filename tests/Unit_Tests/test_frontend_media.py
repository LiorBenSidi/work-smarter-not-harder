"""Guard the frontend wiring for media attachments (Elad's backend: POST /media -> bind -> serve). OWNER: Lior.

The media BACKEND was complete but had no UI. These pin the frontend integration so it can't silently
regress: a file picker on the forum-post + DM composers, a multipart uploader (api() is JSON-only), the
attach calls, and the render of a post's / conversation's attachments.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INDEX = (ROOT / "web" / "templates" / "index.html").read_text(encoding="utf-8")

ACCEPT = "image/png,image/jpeg,image/webp,image/gif,video/mp4"


def test_multipart_uploader_exists_and_is_separate_from_json_api():
    # api() only speaks JSON; uploads must go through a dedicated multipart fetch that still sends the CSRF header.
    assert "async function uploadMedia(file)" in INDEX
    assert "new FormData()" in INDEX and 'fd.append("file", file)' in INDEX
    assert re.search(r'fetch\("/media",\s*\{[^}]*method:\s*"POST"[\s\S]{0,160}X-CSRF-Token', INDEX), \
        "the media upload must POST multipart to /media with the CSRF header"


def test_forum_composer_can_attach_and_post_renders_attachments():
    assert '<input type="file" id="forum-files"' in INDEX and ACCEPT in INDEX
    # after creating a post, upload the picked files and bind their ids to the new post
    assert re.search(r'/forum/posts/"\s*\+\s*post\.id\s*\+\s*"/attachments"', INDEX), \
        "the forum composer must attach uploaded media to the created post"
    # the post detail fetches + renders its attachments
    assert '<div id="post-atts"></div>' in INDEX
    assert re.search(r'/forum/posts/"\s*\+\s*id\s*\+\s*"/attachments"', INDEX)
    assert "function mediaEmbedHtml(att)" in INDEX and "function attsHtml(atts)" in INDEX


def test_dm_composer_can_attach_and_thread_renders_shared_media():
    assert '<input type="file" id="dm-files"' in INDEX
    assert '<div id="dm-atts"></div>' in INDEX
    # send binds uploaded media to the conversation; the thread lists the conversation's shared media
    assert INDEX.count('/messages/" + encodeURIComponent(dmPeer) + "/attachments"') >= 1
    assert re.search(r'/messages/"\s*\+\s*encodeURIComponent\(peer\)\s*\+\s*"/attachments"', INDEX), \
        "the DM thread must load the conversation's shared media"


def test_media_render_is_injection_safe():
    # attachment ids come from the server as opaque hex; the embed builds /media/<id> with encodeURIComponent
    # and images/video load via src (no innerHTML of user text). Pin the encode so an id can't break out.
    assert 'mediaEmbedHtml' in INDEX
    assert re.search(r'"/media/"\s*\+\s*encodeURIComponent\(att\.id\)', INDEX), \
        "media urls must encodeURIComponent the id"
