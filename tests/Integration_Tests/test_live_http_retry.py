"""The live-stack session survives a connection closed mid-request — OWNER: Elad. (#568)

Proves the tolerance that ``System_Tests/_live_http.py`` exists for, against a REAL socket rather than a
mock: a server that accepts a connection and closes it without answering is exactly what gunicorn's
``--max-requests`` worker swap does to whatever request is in flight. A bare ``requests.Session`` fails
that; the live session retries onto a fresh connection and completes.

The pairing matters — asserting only that the live session survives would pass even if the retry were
deleted and the server never dropped anything, so the bare-session leg is what makes this test able to
fail for a real reason.
"""
import importlib.util
import socket
import threading
from pathlib import Path

import pytest

requests = pytest.importorskip("requests")

_HELPER = Path(__file__).resolve().parents[1] / "System_Tests" / "_live_http.py"
_spec = importlib.util.spec_from_file_location("live_http_under_test", str(_HELPER))
_live_http = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_live_http)

_REASON = {200: "OK", 429: "Too Many Requests", 500: "Internal Server Error"}


class DroppingServer:
    """Closes the first ``drops`` connections without responding, then answers with ``status``.

    Mirrors the recycle window: the socket is accepted (the worker is still listening) and then goes
    away before a response is written.
    """

    def __init__(self, drops=1, status=200):
        self.drops = drops
        self.status = status
        self.accepted = 0
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(8)
        self.port = self._sock.getsockname()[1]
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except OSError:                   # the listener was closed by close()
                return
            self.accepted += 1
            with conn:
                if self.accepted <= self.drops:
                    continue                  # the worker went away mid-request
                body = b"ok" if self.status == 200 else b""
                head = (f"HTTP/1.1 {self.status} {_REASON[self.status]}\r\n"
                        f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n").encode()
                try:
                    conn.recv(65536)
                    conn.sendall(head + body)
                except OSError:               # pragma: no cover - client hung up first
                    pass

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}"

    def close(self):
        self._stop.set()
        self._sock.close()
        self._thread.join(timeout=2)


@pytest.fixture
def server_factory():
    made = []

    def make(drops=1, status=200):
        s = DroppingServer(drops=drops, status=status)
        made.append(s)
        return s

    yield make
    for s in made:
        s.close()


def test_a_bare_session_dies_when_the_worker_closes_mid_request(server_factory):
    """The failure the live suites were exposed to — the behaviour being fixed."""
    server = server_factory(drops=1)
    with requests.Session() as bare:
        with pytest.raises(requests.exceptions.ConnectionError):
            bare.get(server.url + "/health", timeout=5)


def test_the_live_session_retries_onto_a_fresh_connection_and_completes(server_factory):
    server = server_factory(drops=1)
    response = _live_http.live_session().get(server.url + "/health", timeout=5)
    assert response.status_code == 200
    assert response.text == "ok"
    assert server.accepted >= 2, "the response came back without the drop being retried"


def test_a_server_that_never_answers_still_fails(server_factory):
    """The retry is a tolerance, not a blindfold: keep dropping and the caller still gets the error."""
    server = server_factory(drops=99)
    with pytest.raises(requests.exceptions.ConnectionError):
        _live_http.live_session().get(server.url + "/health", timeout=5)


@pytest.mark.parametrize("status", [429, 500])
def test_an_http_error_status_is_never_retried_away(server_factory, status):
    """status=0 is the point: a 429 from the rate limiter must still reach the test that expects it."""
    server = server_factory(drops=0, status=status)
    response = _live_http.live_session().get(server.url + "/forum/posts", timeout=5)
    assert response.status_code == status
    assert server.accepted == 1, "an error response was retried — the caller would see the wrong attempt"
