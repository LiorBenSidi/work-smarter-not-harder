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
    def __init__(self, payload, raise_json=False):
        self._payload = payload
        self._raise_json = raise_json

    def raise_for_status(self):
        pass

    def json(self):
        if self._raise_json:
            raise ValueError("no JSON body")
        return self._payload


def test_predict_returns_parsed_json(ai_client, monkeypatch):
    monkeypatch.setattr(ai_client.requests, "post", lambda *a, **k: _Resp({"state": "Ready"}))
    assert ai_client.predict("http://ai:5000", {"x": 1}) == {"state": "Ready"}


def test_predict_returns_none_on_network_error(ai_client, monkeypatch):
    def boom(*a, **k):
        raise ai_client.requests.RequestException("down")

    monkeypatch.setattr(ai_client.requests, "post", boom)
    assert ai_client.predict("http://ai:5000", {"x": 1}) is None


def test_predict_returns_none_on_bad_json(ai_client, monkeypatch):
    monkeypatch.setattr(ai_client.requests, "post", lambda *a, **k: _Resp(None, raise_json=True))
    assert ai_client.predict("http://ai:5000", {"x": 1}) is None
