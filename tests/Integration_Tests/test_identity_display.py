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
    """Two people sharing a display name get distinct identities: both see the same name on the post, but only its actual author is told it is theirs to edit."""
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


def test_suffixed_user_content_shows_display_name_never_the_handle(forum_client):
    """For the account whose name collided, the internal handle differs from the name it shows — so this is where a leak would surface.

    Everything a person reads says the chosen name, never the raw handle, and ownership still resolves correctly.
    """
    _register(forum_client, "sam", "sam1@example.com")                                   # handle "sam"
    h2 = _register(forum_client, "sam", "sam2@example.com").get_json()["username"]        # handle "sam-2"
    assert h2 == "sam-2"
    _login(forum_client, "sam2@example.com")                                             # the suffixed account
    pid = forum_client.post("/forum/posts", json={"title": "t", "body": "b"}).get_json()["post"]["id"]
    forum_client.post("/forum/posts/" + pid + "/comments", json={"body": "mine"})
    p = forum_client.get("/forum/posts/" + pid).get_json()["post"]
    assert p["author"] == "sam" and p["author"] != "sam-2"        # display name, not the internal handle
    comments = forum_client.get("/forum/posts/" + pid + "/comments").get_json()["comments"]   # #331: own endpoint
    assert comments[0]["author"] == "sam"                         # comment author resolved too
    assert p["mine"] is True                                      # and the suffixed account still owns it


def test_dm_conversation_and_thread_expose_the_peer_display_name(messages_client):
    """A conversation carries both the stable handle it is keyed by and the name to show, so the interface can label the thread without guessing at an identifier the user never chose.

    The peer is a COLLIDED account, whose handle ("eve-2") differs from the name it shows ("eve").
    That distinction is the whole point: the earlier version of this test used a peer whose handle and
    display name were the identical string, so dropping the display-name resolution changed nothing and
    it passed either way. Measured with the peer un-suffixed: returning the raw handle as `peer_name`
    on the thread left the whole suite green (measured).
    """
    _register(messages_client, "dan", "dan@example.com")
    _register(messages_client, "eve", "eve1@example.com")                                  # handle "eve"
    handle = _register(messages_client, "eve", "eve2@example.com").get_json()["username"]   # handle "eve-2"
    assert handle == "eve-2", "the collided account must get a suffixed handle for this test to mean anything"
    _login(messages_client, "dan@example.com")
    messages_client.post("/messages", json={"to": handle, "body": "hey eve"})
    convo = messages_client.get("/conversations").get_json()["conversations"][0]
    assert convo["peer"] == handle, "the conversation stays keyed by the stable handle"
    assert convo["peer_name"] == "eve", "the inbox shows the chosen name, never the internal handle"
    thread = messages_client.get("/conversations/" + handle).get_json()
    assert thread["peer_name"] == "eve", "the open thread's header shows the chosen name too"


