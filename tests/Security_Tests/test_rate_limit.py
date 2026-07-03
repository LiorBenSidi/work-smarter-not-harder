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
