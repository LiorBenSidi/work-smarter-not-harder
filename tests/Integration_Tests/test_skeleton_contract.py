"""Skeleton contract checks — guard the architecture invariants the whole team depends on.

These pass on the skeleton and keep passing as the app is built. Owners add the real feature
integration tests (register -> login -> dashboard, web -> ai roundtrip) alongside their code.
"""
import importlib.util
from pathlib import Path

import pytest

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


def test_ai_predict_returns_the_contract_shape():
    # the web -> ai contract (docs/DESIGN.md §3): /predict returns state (str) + proba (dict)
    # + recommendations (list). Behavioural — exercise the real app, don't grep source text.
    pytest.importorskip("flask")
    spec = importlib.util.spec_from_file_location("ai_app_under_test", str(ROOT / "ai" / "app.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    client = module.create_app().test_client()
    resp = client.post("/predict", json={"features": {"sleep_hours": 7}})
    assert resp.status_code == 200
    body = resp.get_json()
    assert isinstance(body["state"], str), "state must be a category string"
    assert isinstance(body["proba"], dict), "proba must be a {category: float} object"
    assert isinstance(body["recommendations"], list), "recommendations must be a list of items"


def test_app_containers_run_via_gunicorn():
    for container in ("web", "ai"):
        dockerfile = (ROOT / container / "Dockerfile").read_text()
        assert "gunicorn" in dockerfile, f"{container} should run via gunicorn (production WSGI)"
