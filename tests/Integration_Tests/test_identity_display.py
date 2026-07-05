"""Identity model (PR2): a NON-unique display name resolves correctly across the forum, DMs and the
notification feed, while the stable internal HANDLE drives identity, ownership and anonymity. OWNER: Lior.

The sharp case throughout: two people who both call themselves the same name get distinct handles, so
what they SEE is the shared name but who-owns-what stays unambiguous.
"""


def _register(client, name, email):
    return client.post("/register", json={"username": name, "password": "s3cretpw!", "email": email})


def _login(client, ident):
    return client.post("/login", json={"username": ident, "password": "s3cretpw!"})


def test_forum_author_shows_display_name_and_mine_is_per_viewer(forum_client):
    h1 = _register(forum_client, "sam", "sam1@example.com").get_json()["username"]
    h2 = _register(forum_client, "sam", "sam2@example.com").get_json()["username"]
    assert h1 != h2                                            # two "sam"s, distinct internal handles
    _login(forum_client, "sam1@example.com")
    pid = forum_client.post("/forum/posts", json={"title": "hi", "body": "from the first sam"}).get_json()["post"]["id"]
    own = forum_client.get("/forum/posts/" + pid).get_json()["post"]
    assert own["author"] == "sam" and own["mine"] is True       # the author sees the name + owns it
    _login(forum_client, "sam2@example.com")
    other = forum_client.get("/forum/posts/" + pid).get_json()["post"]
    assert other["author"] == "sam" and other["mine"] is False  # same shown name, but NOT theirs to edit


def test_anonymous_post_hides_the_name_but_owner_still_sees_mine(forum_client):
    _register(forum_client, "ann", "ann@example.com")
    _register(forum_client, "bob", "bob@example.com")
    _login(forum_client, "ann@example.com")
    pid = forum_client.post("/forum/posts",
                            json={"title": "secret", "body": "anon body", "anonymous": True}).get_json()["post"]["id"]
    own = forum_client.get("/forum/posts/" + pid).get_json()["post"]
    assert own["author"] == "Anonymous" and own["mine"] is True     # owner can still manage their anon post
    _login(forum_client, "bob@example.com")
    other = forum_client.get("/forum/posts/" + pid).get_json()["post"]
    assert other["author"] == "Anonymous" and other["mine"] is False  # never reveals the anon author to others


def test_suffixed_user_content_shows_display_name_never_the_handle(forum_client):
    # The SECOND "sam" has handle "sam-2" but display name "sam" — so this exercises resolution where the
    # handle differs from the shown name. Everything a person sees must say "sam", never the raw "sam-2".
    _register(forum_client, "sam", "sam1@example.com")                                   # handle "sam"
    h2 = _register(forum_client, "sam", "sam2@example.com").get_json()["username"]        # handle "sam-2"
    assert h2 == "sam-2"
    _login(forum_client, "sam2@example.com")                                             # the suffixed account
    pid = forum_client.post("/forum/posts", json={"title": "t", "body": "b"}).get_json()["post"]["id"]
    forum_client.post("/forum/posts/" + pid + "/comments", json={"body": "mine"})
    p = forum_client.get("/forum/posts/" + pid).get_json()["post"]
    assert p["author"] == "sam" and p["author"] != "sam-2"        # display name, not the internal handle
    assert p["comments"][0]["author"] == "sam"                    # comment author resolved too
    assert p["mine"] is True                                      # and the suffixed account still owns it


def test_comment_author_shows_display_name(forum_client):
    _register(forum_client, "cara", "cara@example.com")
    _login(forum_client, "cara@example.com")
    pid = forum_client.post("/forum/posts", json={"title": "t", "body": "b"}).get_json()["post"]["id"]
    forum_client.post("/forum/posts/" + pid + "/comments", json={"body": "nice"})
    p = forum_client.get("/forum/posts/" + pid).get_json()["post"]
    assert p["comments"][0]["author"] == "cara"


def test_dm_conversation_and_thread_expose_the_peer_display_name(messages_client):
    _register(messages_client, "dan", "dan@example.com")
    _register(messages_client, "eve", "eve@example.com")
    _login(messages_client, "dan@example.com")
    messages_client.post("/messages", json={"to": "eve", "body": "hey eve"})
    convo = messages_client.get("/conversations").get_json()["conversations"][0]
    assert convo["peer"] == "eve" and convo["peer_name"] == "eve"   # peer stays the handle; peer_name is shown
    thread = messages_client.get("/conversations/eve").get_json()
    assert thread["peer_name"] == "eve"


def test_vote_notification_carries_the_display_name_in_the_actor_not_the_text(forum_client):
    # The voter's identity lives in the ACTOR field (re-resolved to the current display name on every list),
    # and the text is name-LESS — so a rename can't leave a stale name frozen in the stored text (F1). The
    # client composes "{actor} {text}" at render.
    _register(forum_client, "poster", "poster@example.com")
    _register(forum_client, "voter", "voter@example.com")
    _login(forum_client, "poster@example.com")
    pid = forum_client.post("/forum/posts", json={"title": "t", "body": "b"}).get_json()["post"]["id"]
    _login(forum_client, "voter@example.com")
    forum_client.post("/forum/posts/" + pid + "/vote", json={"value": 1})
    _login(forum_client, "poster@example.com")
    votes = [n for n in forum_client.get("/notifications").get_json()["notifications"] if n["type"] == "vote"]
    assert votes and votes[0]["text"] == "upvoted your post"   # name-less
    assert votes[0]["actor"] == "voter"                        # identity in the actor (live-resolved display name)
