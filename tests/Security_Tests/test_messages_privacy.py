"""Security tests for the DM + notification layer. OWNER: Lior.

The load-bearing property: a direct message is private to its two participants. A third user must not be
able to read someone else's conversation or see someone else's notifications, and the recipient field is
subject to the same NoSQL-injection gate as the rest of auth.
"""
PW = "s3cretpw!"


def _register(client, name):
    return client.post("/register", json={"username": name, "password": PW, "email": f"{name}@ex.com"})


def _login(client, name):
    return client.post("/login", json={"username": name, "password": PW})


def test_a_third_user_cannot_read_a_private_conversation(messages_client):
    c = messages_client
    for n in ("alice", "bob", "carol"):
        _register(c, n)
    _login(c, "alice")
    c.post("/messages", json={"to": "bob", "body": "secret for bob only"})
    # carol tries every angle: naming alice's thread, naming bob's thread, listing her own inbox
    _login(c, "carol")
    for path in ("/conversations/alice", "/conversations/bob"):
        thread = c.get(path).get_json()["messages"]
        # (an `all(body != secret for m in thread)` guard used to sit here; it was vacuously true on
        #  the empty list the next line asserts, so it carried no signal.)
        assert thread == []                                     # carol shares no thread with either
    assert c.get("/conversations").get_json()["conversations"] == []


def test_a_third_user_does_not_receive_others_notifications(messages_client):
    c = messages_client
    for n in ("alice", "bob", "carol"):
        _register(c, n)
    _login(c, "alice")
    c.post("/messages", json={"to": "bob", "body": "hi bob"})    # notifies bob, not carol
    _login(c, "carol")
    data = c.get("/notifications").get_json()
    assert data["notifications"] == [] and data["unread"] == 0


def test_a_delimiter_username_cannot_hijack_another_pairs_thread(messages_client):
    # regression for the thread-id collision: with a "|".join(pair) id, attacker "bob|carol" asking for
    # their thread with "dave" would resolve to the SAME id as bob <-> "carol|dave" and leak it.
    c = messages_client
    for n in ("bob", "carol|dave", "bob|carol", "dave"):
        _register(c, n)
    _login(c, "bob")
    c.post("/messages", json={"to": "carol|dave", "body": "old delimiter would leak this"})
    _login(c, "bob|carol")
    thread = c.get("/conversations/dave").get_json()["messages"]
    assert thread == []                                             # no collision -> attacker sees nothing


# (The `{"to": {"$gt": ""}}` operator-injection recipient is rejected with the identical payload in
#  Negative_Tests, which also asserts the message was never delivered.)


def test_marking_read_only_affects_your_own_notifications(messages_client):
    c = messages_client
    for n in ("alice", "bob", "carol"):
        _register(c, n)
    # both bob and carol get a DM from alice
    _login(c, "alice")
    c.post("/messages", json={"to": "bob", "body": "hey"})
    c.post("/messages", json={"to": "carol", "body": "yo"})
    # bob clears his — carol's must remain unread
    _login(c, "bob")
    c.post("/notifications/read", json={})
    _login(c, "carol")
    assert c.get("/notifications").get_json()["unread"] == 1
