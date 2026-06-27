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


def test_all_three_services_have_healthchecks():
    compose = (ROOT / "docker-compose.yml").read_text()
    assert compose.count("healthcheck:") == 3, "web, ai and db must each define a healthcheck"


def test_ai_predict_returns_the_contract_keys():
    # the web -> ai contract (docs/DESIGN.md §3): /predict must return state + proba + recommendations.
    ai_app = (ROOT / "ai" / "app.py").read_text()
    for key in ("state", "proba", "recommendations"):
        assert f"{key}=" in ai_app, f"ai /predict must return '{key}' (the web->ai contract)"


def test_app_containers_run_via_gunicorn():
    for container in ("web", "ai"):
        dockerfile = (ROOT / container / "Dockerfile").read_text()
        assert "gunicorn" in dockerfile, f"{container} should run via gunicorn (production WSGI)"
