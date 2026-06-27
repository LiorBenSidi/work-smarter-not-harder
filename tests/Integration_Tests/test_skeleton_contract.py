"""Skeleton contract checks — guard the architecture invariants the whole team depends on.

These pass on the skeleton and keep passing as the app is built. Owners add the real feature
integration tests (register -> login -> dashboard, web -> ai roundtrip) alongside their code.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_only_web_publishes_a_host_port():
    compose = (ROOT / "docker-compose.yml").read_text()
    assert "8000:5000" in compose, "web must publish host 8000 -> container 5000"
    # ai/db are internal (`expose`, not `ports`), so the whole file must have exactly one `ports:`.
    assert compose.count("ports:") == 1, "ONLY web may publish a host port — ai/db stay internal"
    assert "5000:5000" not in compose, "never publish host 5000 (macOS AirPlay hijacks it)"


def test_each_app_container_has_a_dockerfile():
    for container in ("web", "ai"):
        assert (ROOT / container / "Dockerfile").is_file(), f"{container}/Dockerfile is missing"
