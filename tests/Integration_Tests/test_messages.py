"""Integration tests for direct messages + notifications over the Flask test client (in-memory stores
injected). OWNER: Lior. Covers the DM round-trip, unread counts, the notification poll + mark-read, the
anti-spam rate limit, input validation, and the auth gate.
"""
PW = "s3cretpw!"


def _register(client, name):
    return client.post("/register", json={"username": name, "password": PW, "email": f"{name}@ex.com"})


def _login(client, name):
    return client.post("/login", json={"username": name, "password": PW})


def _setup(client, *names):
    for n in names:
        _register(client, n)


def test_send_and_read_dm(messages_client):
    c = messages_client
    _setup(c, "alice", "bob")
    _login(c, "alice")
    assert c.post("/messages", json={"to": "bob", "body": "hey bob"}).status_code == 201
    _login(c, "bob")
    thread = c.get("/conversations/alice").get_json()["messages"]
    assert [m["body"] for m in thread] == ["hey bob"]
    assert thread[0]["sender"] == "alice"


def test_conversation_list_and_unread_clears_on_open(messages_client):
    c = messages_client
    _setup(c, "alice", "bob")
    _login(c, "alice")
    c.post("/messages", json={"to": "bob", "body": "one"})
    c.post("/messages", json={"to": "bob", "body": "two"})
    _login(c, "bob")
    convos = c.get("/conversations").get_json()["conversations"]
    assert len(convos) == 1 and convos[0]["peer"] == "alice" and convos[0]["unread"] == 2
    c.get("/conversations/alice")                                    # opening the thread marks read
    assert c.get("/conversations").get_json()["conversations"][0]["unread"] == 0


def test_dm_creates_a_notification_for_the_recipient(messages_client):
    c = messages_client
    _setup(c, "alice", "bob")
    _login(c, "alice")
    c.post("/messages", json={"to": "bob", "body": "ping"})
    _login(c, "bob")
    data = c.get("/notifications").get_json()
    assert data["unread"] == 1
    assert data["notifications"][0]["type"] == "dm"
    assert data["notifications"][0]["actor"] == "alice"


def test_notifications_poll_since_returns_only_newer(messages_client):
    c = messages_client
    _setup(c, "alice", "bob")
    _login(c, "alice")
    c.post("/messages", json={"to": "bob", "body": "first"})
    _login(c, "bob")
    first = c.get("/notifications").get_json()["notifications"][0]
    _login(c, "alice")
    c.post("/messages", json={"to": "bob", "body": "second"})
    _login(c, "bob")
    newer = c.get(f"/notifications?since={first['created_at']}").get_json()["notifications"]
    assert len(newer) == 1                                           # only the notification after the cursor


def test_mark_notifications_read(messages_client):
    c = messages_client
    _setup(c, "alice", "bob")
    _login(c, "alice")
    c.post("/messages", json={"to": "bob", "body": "hi"})
    _login(c, "bob")
    assert c.get("/notifications").get_json()["unread"] == 1
    assert c.post("/notifications/read", json={}).status_code == 200
    assert c.get("/notifications").get_json()["unread"] == 0


def test_mark_read_with_empty_ids_is_a_noop(messages_client):
    # {"ids": []} means "mark these zero notifications" -> must NOT mark the whole feed read
    c = messages_client
    _setup(c, "alice", "bob")
    _login(c, "alice")
    c.post("/messages", json={"to": "bob", "body": "hi"})
    _login(c, "bob")
    assert c.get("/notifications").get_json()["unread"] == 1
    assert c.post("/notifications/read", json={"ids": []}).status_code == 200
    assert c.get("/notifications").get_json()["unread"] == 1


def test_mark_read_specific_ids_only(messages_client):
    c = messages_client
    _setup(c, "alice", "bob", "carol")
    _login(c, "alice")
    c.post("/messages", json={"to": "bob", "body": "from alice"})
    _login(c, "carol")
    c.post("/messages", json={"to": "bob", "body": "from carol"})
    _login(c, "bob")
    notes = c.get("/notifications").get_json()["notifications"]
    one = next(n for n in notes if n["actor"] == "alice")["id"]
    c.post("/notifications/read", json={"ids": [one]})
    assert c.get("/notifications").get_json()["unread"] == 1        # only carol's remains


def test_non_finite_since_returns_all_not_nothing(messages_client):
    # a nan/inf polling cursor must not silently blackhole the feed
    c = messages_client
    _setup(c, "alice", "bob")
    _login(c, "alice")
    c.post("/messages", json={"to": "bob", "body": "hi"})
    _login(c, "bob")
    assert c.get("/notifications?since=nan").get_json()["unread"] == 1
    assert len(c.get("/notifications?since=inf").get_json()["notifications"]) == 1


def test_rate_limit_blocks_a_flood(messages_client):
    c = messages_client
    _setup(c, "alice", "bob")
    _login(c, "alice")
    for _ in range(20):
        assert c.post("/messages", json={"to": "bob", "body": "spam"}).status_code == 201
    assert c.post("/messages", json={"to": "bob", "body": "spam"}).status_code == 429


def test_validation_and_edges(messages_client):
    c = messages_client
    _setup(c, "alice", "bob")
    _login(c, "alice")
    assert c.post("/messages", json={"to": "bob", "body": ""}).status_code == 400        # empty body
    assert c.post("/messages", json={"to": "", "body": "x"}).status_code == 400          # empty recipient
    assert c.post("/messages", json={"body": "x"}).status_code == 400                    # missing recipient
    assert c.post("/messages", json={"to": "alice", "body": "x"}).status_code == 400     # self-message
    assert c.post("/messages", json={"to": "ghost", "body": "x"}).status_code == 404     # unknown recipient


def test_all_endpoints_require_login(messages_client):
    c = messages_client
    assert c.post("/messages", json={"to": "bob", "body": "x"}).status_code == 401
    assert c.get("/conversations").status_code == 401
    assert c.get("/conversations/bob").status_code == 401
    assert c.get("/notifications").status_code == 401
    assert c.post("/notifications/read", json={}).status_code == 401
    assert c.get("/events").status_code == 401   # the SSE stream is auth-gated too (401 before streaming)
