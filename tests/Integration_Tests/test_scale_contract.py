"""Scaling contract guards — OWNER: Elad.

The scaling story (docs/SCALING_REPORT.md) rests on a few invariants that are easy to break by
accident and impossible to notice until the numbers are wrong or the VM is down:

  * the benchmark target must **never** be what production scores with. `bench:cpu_burn` burns CPU on
    purpose; shipping it as the real target would make every prediction slow and meaningless.
  * scaling `ai` out must not publish it. `--scale ai=N` with a `ports:` mapping fails outright on the
    second replica (port collision) and exposes an unauthenticated `/jobs` on the first.
  * the `/jobs` + replicas caveat must stay written down. The job store is per-container, so a scaled
    `ai` would 404 job reads — safe today only because `web` calls `/predict` alone.
"""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _strip_comments(text):
    lines = []
    for line in text.splitlines():
        code = line.split("#", 1)[0].rstrip()
        if code:
            lines.append(code)
    return "\n".join(lines) + "\n"


@pytest.fixture(scope="module")
def scale():
    return _strip_comments((ROOT / "docker-compose.scale.yml").read_text())


@pytest.fixture(scope="module")
def scale_raw():
    return (ROOT / "docker-compose.scale.yml").read_text()


# --------------------------------------------------------------------------- the bench target


def test_the_benchmark_is_never_the_production_target(jobqueue_module):
    assert jobqueue_module.DEFAULT_TARGET == "inference:predict_one"
    assert "bench" not in jobqueue_module.DEFAULT_TARGET


@pytest.mark.parametrize("compose", ["docker-compose.yml", "docker-compose.prod.yml", "docker-compose.test.yml"])
def test_no_shipped_compose_file_points_ai_at_the_benchmark(compose):
    """prod scoring CPU-burn loops instead of the model would be a silent, catastrophic regression."""
    text = _strip_comments((ROOT / compose).read_text())
    assert "bench:cpu_burn" not in text, f"{compose} must not select the benchmark workload"


def test_the_scale_override_defaults_to_the_real_model(scale):
    """The override exists to size the pool; selecting the bench must be an explicit, opt-in env."""
    assert "AI_WORKER_TARGET: ${AI_WORKER_TARGET:-inference:predict_one}" in scale


# --------------------------------------------------------------------------- scaling out safely


def test_the_scale_override_never_publishes_ai(scale):
    """A `ports:` on a scaled service collides on the second replica AND exposes /jobs with no auth."""
    assert "ports:" not in scale


def test_the_scale_override_sizes_both_axes(scale):
    assert "AI_QUEUE_WORKERS" in scale, "the in-container pool size (vertical axis)"
    assert "--workers" in scale, "web gunicorn workers"


def test_web_gets_more_than_one_gunicorn_worker_when_scaled(scale):
    """web is I/O-bound (it waits on ai and Mongo), so processes are the right knob there — unlike
    `ai`, which is pinned to one worker because its job store is in-memory."""
    assert '"${WEB_WORKERS:-4}"' in scale


def test_the_replica_caveat_stays_documented(scale_raw):
    """The one thing a future reader must not have to rediscover: /jobs is not replica-safe."""
    lowered = scale_raw.lower()
    assert "/jobs" in lowered
    assert "replica" in lowered
    assert "/predict" in lowered


def test_the_queue_documents_why_ai_holds_state_in_memory(jobqueue_module):
    doc = jobqueue_module.__doc__ or ""
    assert "in-memory" in doc.lower()


# --------------------------------------------------------------------------- the benchmark payload


def test_the_benchmark_payload_passes_the_predict_validator(ai_app_module):
    """/predict validates the four readiness fields before the queue for EVERY worker target
    (ai/app.py), so a benchmark payload the validator rejects measures the 400 path, not the pool —
    exactly how the script silently broke when the model's field validation landed. Pin the script's
    payload to the validator it must satisfy, for both the plain and the --iterations form."""
    spec = importlib.util.spec_from_file_location(
        "scaling_benchmark_under_test", str(ROOT / "scripts" / "scaling_benchmark.py")
    )
    benchmark = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(benchmark)

    assert ai_app_module._readiness_error(benchmark.READINESS_FIELDS) is None
    with_bench_knob = dict(benchmark.READINESS_FIELDS, iterations=300_000)
    assert ai_app_module._readiness_error(with_bench_knob) is None
    assert len(with_bench_knob) <= ai_app_module.MAX_FEATURES
