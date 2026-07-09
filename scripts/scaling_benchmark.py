"""Measure `/predict` throughput at a fixed concurrency. OWNER: Elad.

Drives a running `ai` (or `web`) endpoint with N concurrent clients for a fixed number of requests and
reports throughput and latency percentiles. Run it once per configuration and compare — that is the
"locust before/after" the design doc asks for, reduced to the one number that matters (requests/sec)
plus the one that catches a lie (p95 latency: a throughput gain paid for by a latency collapse is not
a gain).

    # baseline: one worker in the pool
    AI_QUEUE_WORKERS=1 AI_WORKER_TARGET=bench:cpu_burn docker compose up -d --build
    python scripts/scaling_benchmark.py --url http://localhost:5099/predict --label "pool=1"

    # after: four
    AI_QUEUE_WORKERS=4 ... ; python scripts/scaling_benchmark.py --url ... --label "pool=4"

Deliberately dependency-free (stdlib only): it must run on the VM and in CI without installing locust.
The ramped, user-behaviour load test lives in tests/Stress_Tests/locustfile.py; this is the microscope.
"""
import argparse
import json
import logging
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("benchmark")


def _checked_url(url):
    """Reject anything but http/https before it reaches urlopen.

    `urlopen` honours `file:` and other handlers, so an unvalidated URL is a file-read primitive
    (CWE-22). This script only ever targets a local HTTP endpoint, so pin the scheme rather than
    suppress the warning.
    """
    scheme = urllib.parse.urlparse(url).scheme
    if scheme not in ("http", "https"):
        raise ValueError(f"refusing to open a non-HTTP URL: {url!r}")
    return url


def _one_request(url, payload, timeout):
    """Return (elapsed_seconds, status). Never raises — a failed request is a data point."""
    body = json.dumps(payload).encode()
    request = urllib.request.Request(
        _checked_url(url), data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    started = time.perf_counter()
    try:
        # Scheme is pinned to http/https by _checked_url above, so B310/S310 do not apply.
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310  # nosec B310
            response.read()
            status = response.status
    except urllib.error.HTTPError as exc:
        status = exc.code
    except Exception:  # noqa: BLE001 - a dropped connection is a result, not a crash
        status = 0
    return time.perf_counter() - started, status


def run(url, requests_count, concurrency, iterations, timeout):
    payload = {"features": {"iterations": iterations}} if iterations else {"features": {}}

    # Warm the pool: the first request per worker process pays for the spawn + import. Measuring it
    # would credit the 1-worker run with a saving it does not have at steady state.
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        list(pool.map(lambda _: _one_request(url, payload, timeout), range(concurrency * 2)))

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        results = list(pool.map(lambda _: _one_request(url, payload, timeout), range(requests_count)))
    wall = time.perf_counter() - started

    latencies = sorted(elapsed for elapsed, status in results if status == 200)
    ok = len(latencies)
    return {
        "requests": requests_count,
        "concurrency": concurrency,
        "ok": ok,
        "failed": requests_count - ok,
        "statuses": _tally(status for _, status in results),
        "wall_seconds": round(wall, 3),
        "throughput_rps": round(ok / wall, 2) if wall else 0.0,
        "p50_ms": _pct(latencies, 0.50),
        "p95_ms": _pct(latencies, 0.95),
        "mean_ms": round(statistics.fmean(latencies) * 1000, 1) if latencies else None,
    }


def _tally(statuses):
    counts = {}
    for status in statuses:
        counts[status] = counts.get(status, 0) + 1
    return dict(sorted(counts.items()))


def _pct(sorted_latencies, fraction):
    if not sorted_latencies:
        return None
    index = min(int(len(sorted_latencies) * fraction), len(sorted_latencies) - 1)
    return round(sorted_latencies[index] * 1000, 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:5099/predict")
    parser.add_argument("--requests", type=int, default=200)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--iterations", type=int, default=0, help="cpu_burn work per request (0 = server default)")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--label", default="run")
    args = parser.parse_args()

    result = run(args.url, args.requests, args.concurrency, args.iterations, args.timeout)
    result["label"] = args.label
    logger.info(json.dumps(result, indent=2))
    return 0 if result["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
