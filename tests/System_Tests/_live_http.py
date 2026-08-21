"""A ``requests.Session`` that survives gunicorn's worker recycle — OWNER: Elad. (#568)

``web`` runs gunicorn with ``--max-requests ${WEB_MAX_REQUESTS:-1000} --max-requests-jitter 100`` and a
single worker, so it deliberately retires and replaces that worker roughly once per long-lived run. The
exiting worker closes its KEEP-ALIVE connections gracefully; a browser re-opens and retries that close
transparently, but a bare ``requests.Session`` surfaces it as ``RemoteDisconnected`` -> ``ConnectionError``
and fails whichever test happened to be mid-call. The server is behaving exactly as configured, so the
client is what has to tolerate it.

This is the same defect the stress suite already carries a fix for (``Stress_Tests/test_load.py``, #327,
where it masqueraded as a ``-1`` server drop) and the same one that produced days of "random" browser E2E
failures (#568). Fixed there per-client, twice; this module is the shared version for the live-stack
``E2E_BASE_URL`` suites so the next client does not have to rediscover it.

**Deliberately connection-scope only** (``status=0``): an HTTP response of any status is returned to the
caller untouched, so a 429 from the anti-spam limiter, a 401 from an auth gate or a 500 still fail the
test they should fail. Only a transport-level failure is retried. ``test_fault_isolation.py`` does NOT use
this session — that suite stops containers on purpose and must observe the real drop.
"""
import requests
import urllib3

#: Matches the stress suite's tolerance (#327): a couple of connection-scope attempts with a short
#: backoff — enough to cross a worker swap (sub-second), far too few to hide a server that is really down.
RETRY = urllib3.util.retry.Retry(total=3, connect=3, read=2, redirect=0, status=0,
                                 allowed_methods=None, backoff_factor=0.1)


def live_session(base=None, timeout=15):
    """A Session that retries transport failures, optionally seeded with the CSRF cookie from ``base``.

    Pass ``base`` to have the session GET ``/health`` first, which is what seeds the double-submit
    ``csrf_token`` cookie every unsafe request then needs.
    """
    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(max_retries=RETRY)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    if base:
        session.get(f"{base}/health", timeout=timeout)
    return session
