"""Unit tests for the web->ai client — graceful degradation (DESIGN §5). OWNER: Lior.

`requests.post` is patched so these run with no ai container: a network/HTTP failure OR a 200 with a
non-JSON body must both yield None (the caller then degrades), and a good response is parsed through.
"""
import sys

import pytest


@pytest.fixture
def ai_client(web_app_module):
    return sys.modules["services.ai_client"]


class _Resp:
    def __init__(self, payload, raise_json=False, status_error=None):
        self._payload = payload
        self._raise_json = raise_json
        self._status_error = status_error      # set to simulate a 4xx/5xx from the ai container

    def raise_for_status(self):
        if self._status_error is not None:
            raise self._status_error

    def json(self):
        if self._raise_json:
            raise ValueError("no JSON body")
        return self._payload


def test_predict_posts_the_agreed_request_and_returns_parsed_json(ai_client, monkeypatch):
    """Pin the web->ai REQUEST, not just the response.

    This used to mock `post` with `lambda *a, **k`, discarding every argument — so the only thing it
    really asserted was the mock's own return value. Verified by mutation: pointing `predict` at
    `{ai_url}/WRONGPATH` with a bare `json=features` envelope left the ENTIRE suite green. The ai
    side pins that it *reads* `{"features": ...}`; nothing pinned that web *writes* it — the one
    contract a three-container split cannot afford to leave untested.
    """
    sent = {}

    def _capture(url, **kwargs):
        sent["url"] = url
        sent.update(kwargs)
        return _Resp({"state": "Ready"})

    monkeypatch.setattr(ai_client.requests, "post", _capture)
    assert ai_client.predict("http://ai:5000", {"x": 1}, timeout=17) == {"state": "Ready"}

    assert sent["url"] == "http://ai:5000/predict"        # the route, not just any endpoint
    assert sent["json"] == {"features": {"x": 1}}         # the envelope the ai container unwraps
    assert sent["timeout"] == 17                          # the caller's configured timeout is honoured


def test_predict_defaults_to_the_safe_timeout_floor(ai_client, monkeypatch):
    """The default timeout matches the AI queue's own default, so web does not abandon work the worker is still busy computing."""
    sent = {}

    def _capture(url, **kwargs):
        sent.update(kwargs)
        return _Resp({"state": "Ready"})

    monkeypatch.setattr(ai_client.requests, "post", _capture)
    ai_client.predict("http://ai:5000", {"x": 1})
    assert sent["timeout"] == 30


def test_predict_returns_none_on_network_error(ai_client, monkeypatch):
    """An unreachable AI container yields None rather than an exception, which is what lets the dashboard degrade to a readable message instead of a 500."""
    def boom(*a, **k):
        raise ai_client.requests.RequestException("down")

    monkeypatch.setattr(ai_client.requests, "post", boom)
    assert ai_client.predict("http://ai:5000", {"x": 1}) is None


def test_predict_returns_none_on_bad_json(ai_client, monkeypatch):
    """A 200 carrying an unparseable body is treated as a failure like any other — a malformed reply must not be mistaken for a real prediction."""
    monkeypatch.setattr(ai_client.requests, "post", lambda *a, **k: _Resp(None, raise_json=True))
    assert ai_client.predict("http://ai:5000", {"x": 1}) is None


def test_predict_returns_none_when_the_ai_answers_with_an_error_status(ai_client, monkeypatch):
    """A 5xx from the ai container is a failure, not a prediction — so the caller degrades instead of
    handing an error body to the dashboard as if it were a readiness score.

    Every other failure test here raises BEFORE a response exists (a network error) or breaks the body
    (unparseable JSON). None of them produced a real response carrying a bad STATUS, because the fake's
    raise_for_status was a no-op — so deleting the raise_for_status call from predict() left the whole
    suite green (measured, 1061 passed) and an error page would have been parsed as a result.
    """
    err = ai_client.requests.HTTPError("500 Server Error")
    monkeypatch.setattr(ai_client.requests, "post",
                        lambda *a, **k: _Resp({"detail": "model failed to load"}, status_error=err))
    assert ai_client.predict("http://ai:5000", {"x": 1}) is None
