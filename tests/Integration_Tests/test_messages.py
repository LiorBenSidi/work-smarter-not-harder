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


def test_dm_read_receipt_lifecycle(messages_client):
    # The sender's ticks progress sent -> delivered (recipient loads inbox) -> read (recipient opens thread).
    c = messages_client
    _setup(c, "alice", "bob")
    _login(c, "alice")
    c.post("/messages", json={"to": "bob", "body": "yo"})
    sent = c.get("/conversations/bob").get_json()["messages"][0]     # alice's own view of her sent msg
    assert sent["delivered"] is False and sent["read"] is False       # just sent
    _login(c, "bob")
    c.get("/conversations")                                          # bob loads his inbox -> delivered
    _login(c, "alice")
    delivered = c.get("/conversations/bob").get_json()["messages"][0]
    assert delivered["delivered"] is True and delivered["read"] is False
    _login(c, "bob")
    c.get("/conversations/alice")                                    # bob opens the thread -> read
    _login(c, "alice")
    read = c.get("/conversations/bob").get_json()["messages"][0]
    assert read["read"] is True and read["delivered"] is True


def test_dm_read_always_implies_delivered(messages_client):
    # Opening a thread straight from a notification (without loading the inbox first) must still leave the
    # message delivered=True — a message can never be read-but-not-delivered (the middle tick is never skipped).
    c = messages_client
    _setup(c, "alice", "bob")
    _login(c, "alice")
    c.post("/messages", json={"to": "bob", "body": "hi"})
    _login(c, "bob")
    c.get("/conversations/alice")                                    # open directly, no inbox load
    _login(c, "alice")
    m = c.get("/conversations/bob").get_json()["messages"][0]
    assert m["read"] is True and m["delivered"] is True


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


def test_events_caps_concurrent_streams_and_reserves_a_thread(messages_client):
    # HIGH-fix regression: /events pins one worker thread for the stream's whole lifetime, so a burst of
    # streams could starve the gunicorn pool and hang EVERY request (login, health...). Over the per-worker
    # cap the endpoint must return IMMEDIATELY, holding NO thread, so ordinary requests keep a free thread.
    from routes import messages
    c = messages_client
    _setup(c, "alice")
    _login(c, "alice")
    held = [messages._sse_slots.acquire(blocking=False) for _ in range(messages.EVENTS_MAX_STREAMS)]
    try:
        assert all(held)                                            # every slot in this worker is now taken
        resp = c.get("/events")                                     # over capacity -> must NOT open a stream
        assert resp.status_code == 200 and resp.mimetype == "text/event-stream"
        assert resp.get_data(as_text=True) == "retry: 60000\n\n"    # the degraded 'reconnect later' response
    finally:
        for ok in held:
            if ok:
                messages._sse_slots.release()


def test_events_stream_releases_its_slot_when_it_ends(messages_client, monkeypatch):
    # The slot MUST be freed when the stream ends (or the client disconnects) via the generator's finally,
    # else the cap leaks and the worker slowly strangles itself. EVENTS_MAX_SECONDS=0 ends it immediately.
    from routes import messages
    monkeypatch.setattr(messages, "EVENTS_MAX_SECONDS", 0)
    c = messages_client
    _setup(c, "alice")
    _login(c, "alice")
    body = c.get("/events").get_data(as_text=True)                  # consuming the stream runs its finally
    assert body.startswith("retry: 3000")                          # a real stream opened (not the degraded one)
    regained = [messages._sse_slots.acquire(blocking=False) for _ in range(messages.EVENTS_MAX_STREAMS)]
    for ok in regained:
        if ok:
            messages._sse_slots.release()
    assert all(regained)                                            # all slots re-acquirable -> nothing leaked


def test_sse_cap_is_clamped_below_thread_count_so_streams_cant_starve_the_worker():
    # An SSE stream pins one gthread thread for its whole life. If the cap ever reached --threads, a burst of
    # streams could hold EVERY thread and starve /health -> failed healthcheck -> container restart (a self-
    # inflicted DoS). _safe_stream_cap must clamp the cap to <= threads//2 (>= half the pool always free for
    # requests/health) no matter how EVENTS_MAX_STREAMS is (mis)configured, and never drop below 1.
    from routes import messages
    cap = messages._safe_stream_cap
    assert cap(3, 16) == 3            # the shipped default: safe, unchanged
    assert cap(100, 16) == 8         # wild misconfig: clamped to half the threads, not 100
    assert cap(16, 16) == 8          # equal to the thread count would starve -> clamped to half
    assert cap(3, 2) == 1            # tiny pool: floor at 1 so the app still boots
    assert cap(5, 4) == 2            # general case: never exceeds threads//2
    # invariant across the sane range: the effective cap always leaves >= half the threads for requests/health
    for threads in (2, 4, 8, 16, 32):
        for configured in (1, 3, threads, threads * 5):
            assert 1 <= cap(configured, threads) <= max(1, threads // 2)


def test_events_pushes_a_forum_ping_when_the_forum_rev_changes(messages_client, monkeypatch):
    # Real-time forum (the "wow"): the SSE stream reads forum.get_rev() each tick and pushes `event: forum`
    # when it moves, so every open client re-fetches. Inject a forum whose rev advances once after the
    # stream's baseline read -> exactly one forum ping. Tiny deadline + zero tick keeps the test instant.
    from routes import messages
    monkeypatch.setattr(messages, "EVENTS_MAX_SECONDS", 0.05)
    monkeypatch.setattr(messages, "EVENTS_TICK_SECONDS", 0)
    c = messages_client
    _setup(c, "alice")
    _login(c, "alice")

    class _RevForum:                                                # get_rev(): 0 at baseline, then 1 (one change)
        def __init__(self):
            self._n = 0

        def get_rev(self):
            n = self._n
            self._n = min(self._n + 1, 1)
            return n

    monkeypatch.setattr(messages, "_forum", lambda stub=_RevForum(): stub)
    body = c.get("/events").get_data(as_text=True)
    assert "event: forum" in body                                   # the forum change pushed a forum ping
    assert "event: notify" not in body                              # no notifications happened -> no false notify ping


def test_events_does_not_push_forum_when_the_rev_is_steady(messages_client, monkeypatch):
    # No forum change -> no forum ping (the stream must not spam every client on keepalive ticks).
    from routes import messages
    monkeypatch.setattr(messages, "EVENTS_MAX_SECONDS", 0.05)
    monkeypatch.setattr(messages, "EVENTS_TICK_SECONDS", 0)
    c = messages_client
    _setup(c, "alice")
    _login(c, "alice")
    monkeypatch.setattr(messages, "_forum", lambda: type("_Steady", (), {"get_rev": lambda self: 7})())
    body = c.get("/events").get_data(as_text=True)
    assert "event: forum" not in body                               # steady rev -> no ping
    assert ": keepalive" in body                                    # ...just keepalives


# ---- directory search for the DM picker (GET /users/search) ----
import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_search_throttle(messages_client):
    # the search throttle is module-global (per-worker); reset it each test so ordering can't leak counts.
    # Depends on messages_client so the app (and thus `routes` in sys.modules) is built before this imports it.
    from routes import messages
    messages._search_hits.clear()
    yield


def test_user_search_finds_by_username(messages_client):
    c = messages_client
    _setup(c, "alice", "marco_r", "marina")
    _login(c, "alice")
    names = sorted(r["username"] for r in c.get("/users/search?q=mar").get_json()["results"])
    assert names == ["marco_r", "marina"]


def test_user_search_excludes_the_caller(messages_client):
    c = messages_client
    _setup(c, "maya", "marco_r")
    _login(c, "maya")
    names = [r["username"] for r in c.get("/users/search?q=ma").get_json()["results"]]
    assert "maya" not in names and "marco_r" in names               # you never find yourself


def test_user_search_too_short_is_empty_200(messages_client):
    c = messages_client
    _setup(c, "alice", "bob")
    _login(c, "alice")
    r = c.get("/users/search?q=a")
    assert r.status_code == 200 and r.get_json()["results"] == []   # 1 char -> nothing, but not an error


def test_user_search_requires_login(messages_client):
    assert messages_client.get("/users/search?q=ab").status_code == 401


def test_user_search_returns_no_pii(messages_client):
    c = messages_client
    _setup(c, "alice", "bob")
    _login(c, "alice")
    resp = c.get("/users/search?q=bo")
    assert "@ex.com" not in resp.get_data(as_text=True)             # emails never leave the server
    for r in resp.get_json()["results"]:
        assert set(r) == {"username", "display_name"}


def test_user_search_caps_results_at_eight(messages_client):
    c = messages_client
    _setup(c, "alice", *[f"runner{i:02d}" for i in range(12)])
    _login(c, "alice")
    assert len(c.get("/users/search?q=runner").get_json()["results"]) == 8


def test_user_search_regex_metacharacters_are_literal(messages_client):
    c = messages_client
    _setup(c, "alice", "bob")
    _login(c, "alice")
    assert c.get("/users/search?q=.*").get_json()["results"] == []  # ".*" is literal, not a match-everyone wildcard


def test_user_search_is_rate_limited(messages_client):
    from routes import messages
    c = messages_client
    _setup(c, "alice", "bob")
    _login(c, "alice")
    codes = [c.get("/users/search?q=bo").status_code for _ in range(messages.SEARCH_RATE_MAX + 5)]
    assert codes[0] == 200 and 429 in codes                        # a scripted flood eventually trips the throttle


# ---- Forum push resilience (#342) -------------------------------------------------------------
# A transient forum-rev read failure must not disable the forum push. It used to: any exception set
# forum_rev=None, and the `is not None` guard then skipped the forum check for the stream's whole 90s
# life. Silently — the baseline read logged nothing — while the stream stayed OPEN and notify kept
# working, so neither the log nor the client's readyState check could reveal it. Elad hit exactly this
# (#342 round 2): stream open, no forum refetch for 3+ minutes, no warning.
#
# get_rev() genuinely can raise: db.forum_get_rev swallows its own errors, but the store's
# _resolve() -> get_db(MONGO_URI) does not — one Mongo hiccup at stream open was enough.


class _ScriptedForum:
    """A forum store whose get_rev() is scripted per call, so a read can fail and a change can land
    at an exact point in the stream's life. Only get_rev is exercised by the SSE path."""

    def __init__(self, revs, fail_on_calls=()):
        self.revs = revs                      # rev value returned by call N (last value repeats)
        self.fail_on_calls = set(fail_on_calls)
        self.calls = 0

    def get_rev(self):
        self.calls += 1
        if self.calls in self.fail_on_calls:
            raise RuntimeError("simulated Mongo hiccup inside the store's _resolve()")
        return self.revs[min(self.calls, len(self.revs)) - 1]


def _stream_with(monkeypatch, make_client, fake_users, fake_messages, fake_notifications, forum):
    from routes import messages
    monkeypatch.setattr(messages, "EVENTS_MAX_SECONDS", 1)
    monkeypatch.setattr(messages, "EVENTS_TICK_SECONDS", 0.05)
    c = make_client(fake_users, forum=forum, messages=fake_messages, notifications=fake_notifications)
    _register(c, "alice")
    _login(c, "alice")
    return c.get("/events").get_data(as_text=True)


def test_events_pushes_forum_when_the_rev_moves(monkeypatch, make_client, fake_users, fake_messages,
                                                fake_notifications):
    # The control for the two regressions below: a healthy stream MUST push when the rev moves. Without
    # this passing, "no push" in those tests would prove nothing (a broken harness looks identical).
    forum = _ScriptedForum(revs=[0, 1])                              # baseline 0, then someone posts
    body = _stream_with(monkeypatch, make_client, fake_users, fake_messages, fake_notifications, forum)
    assert body.startswith("retry: 3000")                            # a real stream (not the at-capacity one)
    assert "event: forum" in body


def test_events_recovers_when_the_rev_baseline_read_fails(monkeypatch, make_client, fake_users,
                                                          fake_messages, fake_notifications):
    # #342: the baseline read raises (Mongo hiccup at stream open), then recovers. A change AFTER the
    # baseline is re-established must still push. The old code left forum_rev=None forever -> silence.
    forum = _ScriptedForum(revs=[0, 0, 1], fail_on_calls=[1])        # call 1 raises; rebaseline at 0; then 1
    body = _stream_with(monkeypatch, make_client, fake_users, fake_messages, fake_notifications, forum)
    assert body.startswith("retry: 3000")
    assert "event: forum" in body, "a stream whose baseline read failed never pushed again"


def test_events_recovers_when_a_rev_tick_read_fails(monkeypatch, make_client, fake_users, fake_messages,
                                                    fake_notifications):
    # Same defect on the tick path. The failed read must keep the LAST known baseline (not reset it), so
    # the very next successful read still sees the change and pushes it — nothing is lost to one hiccup.
    forum = _ScriptedForum(revs=[0, 1], fail_on_calls=[2])           # baseline 0; first tick raises; then 1
    body = _stream_with(monkeypatch, make_client, fake_users, fake_messages, fake_notifications, forum)
    assert body.startswith("retry: 3000")
    assert "event: forum" in body, "one failed tick read disabled the push for the rest of the stream"


def test_events_survives_a_rev_read_that_never_recovers(monkeypatch, make_client, fake_users,
                                                        fake_messages, fake_notifications):
    # The forum rev being unreadable for the whole stream must degrade to "no forum pushes", never to a
    # dead stream: DM/notify keepalives keep flowing and the client's poll backstop covers the forum.
    forum = _ScriptedForum(revs=[0], fail_on_calls=range(1, 100))
    body = _stream_with(monkeypatch, make_client, fake_users, fake_messages, fake_notifications, forum)
    assert body.startswith("retry: 3000")
    assert ": keepalive" in body                                     # the stream lived out its full life
