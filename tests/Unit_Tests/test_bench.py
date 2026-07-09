"""Unit tests for the scaling benchmark's workload — OWNER: Elad.

`ai/bench.py:cpu_burn` is a measuring instrument: the before/after tables in docs/SCALING_REPORT.md
are only trustworthy if the workload is identical across runs. So the properties that matter are
*determinism* and *proportionality* — the same input must cost the same work and produce the same
answer, and twice the iterations must cost about twice the time. If either drifts, a future
before/after compares two different workloads and the "speedup" is an artefact.
"""
import time

import pytest


@pytest.fixture(scope="module")
def bench():
    import importlib.util
    import sys
    from pathlib import Path

    if "bench" in sys.modules:
        return sys.modules["bench"]
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("bench", str(root / "ai" / "bench.py"))
    module = importlib.util.module_from_spec(spec)
    # Registered under its real name so `pickle` can resolve `cpu_burn` by reference — the same way a
    # worker process resolves it when AI_WORKER_TARGET points here.
    sys.modules["bench"] = module
    spec.loader.exec_module(module)
    return module


def test_cpu_burn_returns_the_web_ai_contract_shape(bench):
    """It stands in for the model, so `web` (and the queue's tests) must not notice the difference."""
    result = bench.cpu_burn({"iterations": 100})
    assert {"state", "proba", "recommendations"} <= set(result)
    assert isinstance(result["state"], str)
    assert isinstance(result["proba"], dict)
    assert isinstance(result["recommendations"], list)


def test_cpu_burn_marks_itself_as_a_benchmark(bench):
    """So a benchmark response can never be mistaken for a real prediction in a log or a report."""
    assert bench.cpu_burn({"iterations": 100})["benchmark"] is True


def test_cpu_burn_is_deterministic(bench):
    """Same input, same checksum — otherwise the workload is not a fixed unit of measurement."""
    first = bench.cpu_burn({"iterations": 5000})
    second = bench.cpu_burn({"iterations": 5000})
    assert first["checksum"] == second["checksum"]
    assert first["iterations"] == second["iterations"] == 5000


def test_cpu_burn_actually_scales_with_its_work_parameter(bench):
    """The knob must control real work. If `iterations` were ignored, every before/after row would be
    measuring the same (tiny) constant and the speedups would be noise."""
    started = time.perf_counter()
    bench.cpu_burn({"iterations": 20_000})
    small = time.perf_counter() - started

    started = time.perf_counter()
    bench.cpu_burn({"iterations": 200_000})
    large = time.perf_counter() - started

    assert large > small * 3, f"10x the iterations cost only {large / max(small, 1e-9):.1f}x the time"


def test_a_different_iteration_count_is_a_different_workload(bench):
    assert bench.cpu_burn({"iterations": 1000})["checksum"] != bench.cpu_burn({"iterations": 2000})["checksum"]


@pytest.mark.parametrize("junk", [None, 0, -5, "1000", 3.5, True])
def test_a_junk_iteration_value_falls_back_to_the_default(bench, junk):
    """A hostile or typo'd `iterations` must not produce a zero-work request (which would silently
    turn the benchmark into a no-op and report a fake speedup)."""
    result = bench.cpu_burn({"iterations": junk})
    assert result["iterations"] == bench.DEFAULT_ITERATIONS


def test_the_env_default_sizes_the_workload(bench, monkeypatch):
    monkeypatch.setenv("BENCH_ITERATIONS", "1234")
    assert bench.cpu_burn({})["iterations"] == 1234


@pytest.mark.parametrize("junk", ["", "abc", "0", "-1"])
def test_a_junk_env_value_falls_back_to_the_default(bench, monkeypatch, junk):
    monkeypatch.setenv("BENCH_ITERATIONS", junk)
    assert bench.cpu_burn({})["iterations"] == bench.DEFAULT_ITERATIONS


def test_an_explicit_iteration_count_overrides_the_env(bench, monkeypatch):
    monkeypatch.setenv("BENCH_ITERATIONS", "999999")
    assert bench.cpu_burn({"iterations": 50})["iterations"] == 50


def test_cpu_burn_is_picklable_as_a_pool_target(bench):
    """It runs in a worker process exactly like `predict_one`, so it must resolve by name."""
    import pickle

    assert pickle.loads(pickle.dumps(bench.cpu_burn)) is bench.cpu_burn
    assert pickle.loads(pickle.dumps(bench.cpu_burn({"iterations": 10})))["benchmark"] is True
