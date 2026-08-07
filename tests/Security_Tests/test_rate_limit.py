"""Security tests: the auth routes are rate-limited (anti-brute-force / anti-spam, §2.7) via
flask-limiter. `rate_limited_client` turns the limiter ON (the rest of the suite runs with it off).
OWNER: Lior.
"""


def test_login_is_rate_limited_after_a_flood(rate_limited_client):
    """Password-guessing from one IP is throttled at 20/min, so a brute-force run is cut off regardless of how wrong the credentials are."""
    c = rate_limited_client
    last = None
    for _ in range(25):
        last = c.post("/login", json={"username": "nobody", "password": "wrongpass"})
    assert last.status_code == 429


def test_register_is_rate_limited_after_a_flood(rate_limited_client):
    """Bulk account creation is capped at 5/min, blunting both signup spam and the confirm-email burn it would inflict on the Brevo daily quota."""
    c = rate_limited_client
    last = None
    for i in range(15):
        last = c.post("/register", json={"username": f"user{i:03d}", "password": "s3cretpw!",
                                         "email": f"u{i}@ex.com"})
    assert last.status_code == 429


def test_forgot_password_is_rate_limited_after_a_flood(rate_limited_client):
    """This route emails a reset link with NO auth required, so its 5/min cap is the only thing stopping it being used to mailbomb a victim's inbox or drain the mail quota."""
    # Always 200-bodied (enumeration-safe) until the cap, so the 429 is the only observable difference.
    c = rate_limited_client
    last = None
    for _ in range(15):
        last = c.post("/forgot-password", json={"email": "victim@example.com"})
    assert last.status_code == 429


def test_checkin_is_rate_limited_after_a_flood(make_client, fake_users, fake_profiles, fake_history, monkeypatch):
    """Check-in reaches the AI queue, so a 30/min fence stops one client hogging predictions from everyone else."""
    # The queue's own 503 is the real backstop; this is the fairness fence in front of it.
    # AI is mocked so the cap — not an AI error — is what trips.
    import sys
    monkeypatch.setattr(sys.modules["services.ai_client"], "predict",
                        lambda url, features, **kw: {"state": "Ready", "calories": 2000})
    c = make_client(fake_users, fake_profiles, history=fake_history)
    app = c.raw.application
    app.config["RATELIMIT_ENABLED"] = True
    from ratelimit import limiter
    with app.app_context():
        try:
            limiter.reset()
        except Exception:
            pass
    c.post("/register", json={"username": "floodcheck", "password": "s3cretpw!", "email": "fc@ex.com"})
    c.post("/login", json={"username": "floodcheck", "password": "s3cretpw!"})
    metrics = {"sleep_hours": 7.5, "resting_hr": 55, "fatigue": 3, "soreness": 2, "training_load": 6}
    last = None
    for _ in range(35):
        last = c.post("/checkin", json=metrics)
    assert last.status_code == 429


def test_traffic_under_the_login_cap_is_not_rate_limited(rate_limited_client):
    """The failable complement to the flood tests: with the limiter ON, ordinary use must NOT trip it — this fails if anyone sets a cap low enough to throttle real users."""
    # /login is 20/min, so 15 attempts stay well under. Mutation-proved: dropping /login to
    # "5 per minute" makes the 6th of these return 429. (The prior version drove the limiter-OFF
    # `client` and asserted `!= 429`, which no code path could produce — it could not fail.)
    c = rate_limited_client
    for i in range(15):
        r = c.post("/login", json={"username": "nobody", "password": "wrongpass"})
        assert r.status_code != 429, f"login {i + 1}/15 (under the 20/min cap) was throttled — cap set too low"


# --- Forum public routes (OWNER: Elad). auth is already limited above; DM has its own anti-spam.
# These lock the forum anti-spam contract: a teammate loosening/removing a cap fails this suite in CI.
def _login_forum(c):
    # register+login stay well under the auth caps (5/min register, 20/min login), so they never 429.
    c.post("/register", json={"username": "flooder", "password": "s3cretpw!", "email": "f@ex.com"})
    c.post("/login", json={"username": "flooder", "password": "s3cretpw!"})


def test_create_post_is_rate_limited_after_a_flood(rate_limited_forum_client):
    """Bulk post spam from one IP is throttled at 10/min, so the feed cannot be flooded faster than it can be read."""
    c = rate_limited_forum_client
    _login_forum(c)
    last = None
    for i in range(15):
        last = c.post("/forum/posts", json={"title": f"t{i}", "body": "hello there"})
    assert last.status_code == 429


def test_vote_is_rate_limited_after_a_flood(rate_limited_forum_client):
    """Toggling a vote in a tight loop is capped at 60/min, so one client cannot churn a post's score."""
    c = rate_limited_forum_client
    _login_forum(c)
    pid = c.post("/forum/posts", json={"title": "votee", "body": "hello there"}).get_json()["post"]["id"]
    last = None
    for _ in range(65):
        last = c.post(f"/forum/posts/{pid}/vote", json={"value": 1})
    assert last.status_code == 429


def test_comment_flood_is_rate_limited(rate_limited_forum_client):
    """Comment flooding on a single post is throttled at 20/min, so a discussion cannot be buried by one IP."""
    c = rate_limited_forum_client
    _login_forum(c)
    pid = c.post("/forum/posts", json={"title": "spammee", "body": "hello there"}).get_json()["post"]["id"]
    last = None
    for i in range(25):
        last = c.post(f"/forum/posts/{pid}/comments", json={"body": f"spam {i}"})
    assert last.status_code == 429


def test_media_upload_is_rate_limited_after_a_flood(rate_limited_media_client):
    """The per-file 10 MB cap alone leaves total disk use unbounded — a 20/min upload cap is what actually bounds an authenticated flood (issue #313)."""
    import io
    c = rate_limited_media_client
    _login_forum(c)
    last = None
    for _ in range(25):
        last = c.post("/media", data={"file": (io.BytesIO(b"\x89PNG\r\n\x1a\nx"), "p.png", "image/png")})
    assert last.status_code == 429


# Removed: test_normal_forum_traffic_is_not_rate_limited drove the *unlimited* forum_client and
# asserted != 429. With RATELIMIT_ENABLED off there is no code path that can return 429, so it could
# not fail for a real reason. The caps themselves are proven by the flood tests above, which use the
# rate_limited_* clients.
