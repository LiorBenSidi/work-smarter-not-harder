"""Web smoke test — the web app boots and serves `/health`.

A universal invariant every owner's work must preserve: if `create_app()` or the `/health`
route breaks, CI catches it immediately (the compose healthcheck depends on `/health`). This
pairs with the ai `/predict` contract test (test_skeleton_contract.py) so *both* app containers
are behaviourally smoke-tested from day one.

Behavioural (Flask test client), not a source grep. Flask is required (CI installs web/requirements);
where it isn't available the test skips rather than failing. Keep the apps bootable for tests
without Docker or the baked model — load heavy resources lazily; `/health` stays trivial.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _web_client():
    # web/app.py imports `config` + `routes.*`, so put web/ on sys.path while loading it.
    web_dir = ROOT / "web"
    sys.path.insert(0, str(web_dir))
    try:
        spec = importlib.util.spec_from_file_location("web_app_under_test", str(web_dir / "app.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.create_app().test_client()
    finally:
        sys.path.remove(str(web_dir))


def test_web_boots_and_serves_health():
    pytest.importorskip("flask")
    resp = _web_client().get("/health")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok", "service": "web"}
