"""Readiness endpoint (`/ready`) — the DB-ping gate used by the post-deploy check + external monitor.

Distinct from `/health` (liveness, Mongo-independent by course rule): `/ready` returns 503 when the
database is unreachable, so a green deploy proves the whole stack serves — not just that web answers.
"""
from unittest.mock import MagicMock, patch


def test_ready_200_when_db_ping_succeeds(make_client):
    client = make_client()
    handle = MagicMock()
    handle.command.return_value = {"ok": 1.0}
    with patch("services.db.get_db", return_value=handle):
        resp = client.get("/ready")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ready"
    handle.command.assert_called_once_with("ping")


def test_ready_503_when_db_unreachable(make_client):
    client = make_client()
    with patch("services.db.get_db", side_effect=Exception("no route to mongo")):
        resp = client.get("/ready")
    assert resp.status_code == 503
    assert resp.get_json()["status"] == "degraded"


def test_health_and_ready_are_distinct(make_client):
    # /health = liveness (Mongo-independent, course rule); /ready = readiness (reflects a DB outage).
    client = make_client()
    with patch("services.db.get_db", side_effect=Exception("db down")):
        assert client.get("/health").status_code == 200   # liveness unaffected
        assert client.get("/ready").status_code == 503     # readiness reflects the outage
