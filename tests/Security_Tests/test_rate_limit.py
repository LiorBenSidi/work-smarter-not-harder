"""Security tests: the auth routes are rate-limited (anti-brute-force / anti-spam, §2.7) via
flask-limiter. `rate_limited_client` turns the limiter ON (the rest of the suite runs with it off).
OWNER: Lior.
"""


def test_login_is_rate_limited_after_a_flood(rate_limited_client):
    c = rate_limited_client
    # 20/min on /login: password-guessing from one IP is throttled regardless of (wrong) credentials
    last = None
    for _ in range(25):
        last = c.post("/login", json={"username": "nobody", "password": "wrongpass"})
    assert last.status_code == 429


def test_register_is_rate_limited_after_a_flood(rate_limited_client):
    c = rate_limited_client
    # 10/min on /register: bulk account creation from one IP is throttled
    last = None
    for i in range(15):
        last = c.post("/register", json={"username": f"user{i:03d}", "password": "s3cretpw!",
                                         "email": f"u{i}@ex.com"})
    assert last.status_code == 429


def test_normal_traffic_is_not_rate_limited(client):
    # the default client (limiter OFF) proves the suite isn't throttled — a handful of logins never 429
    for _ in range(30):
        assert client.post("/login", json={"username": "nobody", "password": "wrongpass"}).status_code != 429


# --- Forum public routes (OWNER: Elad). auth is already limited above; DM has its own anti-spam.
# These lock the forum anti-spam contract: a teammate loosening/removing a cap fails this suite in CI.
def _login_forum(c):
    # register+login stay well under the auth caps (10/min register, 20/min login), so they never 429.
    c.post("/register", json={"username": "flooder", "password": "s3cretpw!", "email": "f@ex.com"})
    c.post("/login", json={"username": "flooder", "password": "s3cretpw!"})


def test_create_post_is_rate_limited_after_a_flood(rate_limited_forum_client):
    c = rate_limited_forum_client
    _login_forum(c)
    # 10/min on POST /forum/posts: bulk post spam from one IP is throttled
    last = None
    for i in range(15):
        last = c.post("/forum/posts", json={"title": f"t{i}", "body": "hello there"})
    assert last.status_code == 429


def test_vote_is_rate_limited_after_a_flood(rate_limited_forum_client):
    c = rate_limited_forum_client
    _login_forum(c)
    pid = c.post("/forum/posts", json={"title": "votee", "body": "hello there"}).get_json()["post"]["id"]
    # 60/min on the vote route: toggling a vote in a tight loop from one IP is throttled
    last = None
    for _ in range(65):
        last = c.post(f"/forum/posts/{pid}/vote", json={"value": 1})
    assert last.status_code == 429


def test_normal_forum_traffic_is_not_rate_limited(forum_client):
    # the default forum_client (limiter OFF) — a handful of posts never 429 (the caps are opt-in)
    forum_client.post("/register", json={"username": "regular", "password": "s3cretpw!", "email": "r@ex.com"})
    forum_client.post("/login", json={"username": "regular", "password": "s3cretpw!"})
    for i in range(15):
        assert forum_client.post("/forum/posts", json={"title": f"p{i}", "body": "hello there"}).status_code != 429
