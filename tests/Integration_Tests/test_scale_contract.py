"""Scaling contract guards — OWNER: Elad.

The scaling story (docs/SCALING_REPORT.md) rests on a few invariants that are easy to break by
accident and impossible to notice until the numbers are wrong or the VM is down:

  * the benchmark target must **never** be what production scores with. `bench:cpu_burn` burns CPU on
    purpose; shipping it as the real target would make every prediction slow and meaningless.
  * scaling `ai` out must not publish it. `--scale ai=N` with a `ports:` mapping fails outright on the
    second replica (port collision) and exposes an unauthenticated `/jobs` on the first.
  * `web` must keep calling `/predict` alone. The job store is per-container, so a scaled `ai` would
    404 job reads round-robined to a replica that never saw the job. Scaling out is safe *because* of
    that call-site restraint, so the restraint itself is what gets pinned here.

The model-seam constant (`DEFAULT_TARGET == "inference:predict_one"`) is pinned once, in
`test_ai_queue_contract.py::test_the_model_seam_exists_with_the_name_the_pool_resolves`, which also
resolves it — not repeated here. Likewise `ai`'s one-gunicorn-worker rule lives in that file.
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


# --------------------------------------------------------------------------- the bench target


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


def test_web_never_calls_the_replica_unsafe_job_endpoints():
    """What actually makes `--scale ai=N` safe: `web` talks to `/predict` and nothing else.

    `/jobs` is per-container state — a read round-robins to a replica that never saw the job and
    404s. Previously this file asserted that the caveat was *written in a comment*, which a reword
    breaks and a real regression does not. Pin the call site instead: if anyone ever wires `web` to
    `/jobs`, scaling out starts losing results, and this fails.
    """
    web_sources = [p for p in (ROOT / "web").rglob("*.py")]
    assert web_sources, "expected to find the web package"

    offenders = []
    for path in web_sources:
        text = path.read_text(encoding="utf-8")
        for number, line in enumerate(text.splitlines(), start=1):
            code = line.split("#", 1)[0]
            if '"/jobs' in code or "'/jobs" in code or "/jobs/" in code:
                offenders.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()}")

    assert offenders == [], (
        "web must reach ai only through /predict — /jobs is not replica-safe:\n" + "\n".join(offenders)
    )


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
