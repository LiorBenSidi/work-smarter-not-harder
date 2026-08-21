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
    suite green (measured) and an error page would have been parsed as a result.
    """
    err = ai_client.requests.HTTPError("500 Server Error")
    monkeypatch.setattr(ai_client.requests, "post",
                        lambda *a, **k: _Resp({"detail": "model failed to load"}, status_error=err))
    assert ai_client.predict("http://ai:5000", {"x": 1}) is None


# ---------------------------------------------------------------------------
# build_features — the single place the /predict body is assembled (#566).
# Three routes used to build it independently; the translation below has to
# happen for all of them or the balance analysis silently sees nothing.
# ---------------------------------------------------------------------------

def test_build_features_merges_profile_and_metrics(ai_client):
    """The payload is profile context plus today's metrics — the behaviour the three call sites had."""
    out = ai_client.build_features({"age": 30, "goal": "gain"}, {"fatigue": 4})
    assert out == {"age": 30, "goal": "gain", "fatigue": 4}


def test_build_features_tolerates_a_missing_profile(ai_client):
    """A user who has not filled a profile must still be scored on metrics alone, never crash."""
    assert ai_client.build_features(None, {"fatigue": 4}) == {"fatigue": 4}


def test_build_features_passes_extra_keys_through(ai_client):
    """/dashboard sends `history` alongside; the builder must not swallow caller-supplied extras."""
    out = ai_client.build_features({"age": 30}, {"fatigue": 4}, history=[{"assessment": "Ready"}])
    assert out["history"] == [{"assessment": "Ready"}]


def test_build_features_translates_training_program_to_performed(ai_client):
    """The profile stores {group: sets}; ai/recommendations.py reads features["performed"] as a flat
    list. Getting this wrong is invisible — the analysis just returns nothing — so assert the shape."""
    out = ai_client.build_features({"training_program": {"chest": 12, "back": 6}}, {"fatigue": 4})
    assert out["performed"] == [{"muscle_group": "chest", "sets": 12},
                                {"muscle_group": "back", "sets": 6}]


def test_build_features_does_not_leak_the_profile_key_onto_the_wire(ai_client):
    """`training_program` is web's vocabulary, `performed` is ai's. Sending both would put a second
    name for the same data on a contract that already has one."""
    out = ai_client.build_features({"training_program": {"chest": 12}}, {"fatigue": 4})
    assert "training_program" not in out


def test_build_features_omits_performed_when_there_is_no_program(ai_client):
    """Every profile saved before #566 has no programme; the analysis must then contribute nothing
    rather than receive an empty list it would have to special-case."""
    assert "performed" not in ai_client.build_features({"age": 30}, {"fatigue": 4})


def test_build_features_omits_performed_for_an_empty_program(ai_client):
    """An athlete who cleared every box has said nothing, not "I train zero sets of everything"."""
    assert "performed" not in ai_client.build_features({"training_program": {}}, {"fatigue": 4})


def test_metrics_win_over_a_same_named_profile_key(ai_client):
    """Today's check-in is the fresher fact; the original `{**profile, **metrics}` ordering said so
    and the builder must keep saying so."""
    out = ai_client.build_features({"training_load": 2}, {"training_load": 9})
    assert out["training_load"] == 9
