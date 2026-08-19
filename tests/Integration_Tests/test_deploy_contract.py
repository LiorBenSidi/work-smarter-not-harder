"""Deploy / harness contract guards — OWNER: Elad.

`test_skeleton_contract.py` locks the DEV compose invariants the whole team shares. This file locks
the parts of the deployment lane that a well-meaning change elsewhere can silently break, so the
breakage surfaces as a red CI run on the PR instead of as a dead VM after a merge to main:

  * the PROD stack: Caddy is the only public surface; web/ai/db never publish a port; the VM PULLS
    pinned GHCR images and never builds them (assignment R5.2).
  * the TEST stack: the cross-container test-runner exists, is one-shot, publishes nothing, and points
    at the THROWAWAY `worksmarter_test` database — never dev/prod data.
  * the CI/CD pipeline shape: tests gate the build, the build gates the deploy, the deploy is gated on
    push-to-main + the DEPLOY_ENABLED switch, and the post-deploy health check + auto-rollback survive.
  * the media volume: attachment bytes live on a volume mounted by `web` alone.

They are cheap text assertions on the committed files (no Docker, no live stack), so they run in the
normal per-PR CI gate. Behaviour of the media/rate-limit code itself is covered by
tests/Security_Tests/test_media_limits.py and test_rate_limit.py.
"""
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def prod():
    return _strip_comments((ROOT / "docker-compose.prod.yml").read_text())


def _strip_comments(text):
    """Drop whole-line and trailing `#` comments, so a directive mentioned in prose (e.g. the header's
    "no `ports:`") can never satisfy — or trip — an assertion about the actual YAML."""
    lines = []
    for line in text.splitlines():
        code = line.split("#", 1)[0].rstrip()
        if code:
            lines.append(code)
    return "\n".join(lines) + "\n"


@pytest.fixture(scope="module")
def dev_stack():
    return _strip_comments((ROOT / "docker-compose.yml").read_text())


@pytest.fixture(scope="module")
def test_stack():
    return _strip_comments((ROOT / "docker-compose.test.yml").read_text())


@pytest.fixture(scope="module")
def ci():
    return (ROOT / ".github" / "workflows" / "ci.yml").read_text()


# --------------------------------------------------------------------------- prod stack (the VM)

def test_prod_publishes_only_caddy(prod):
    # Caddy terminates TLS and is the ONLY thing on the public internet; web/ai/db stay on the
    # internal network. A stray `ports:` on web would expose the app on :5000, bypassing HTTPS.
    assert prod.count("ports:") == 1, "ONLY caddy may publish host ports in prod"
    assert '"80:80"' in prod and '"443:443"' in prod, "caddy must serve :80 (ACME + redirect) and :443"


def test_prod_never_publishes_the_app_or_db_directly(prod):
    for leaked in ('"8000:5000"', '"5000:5000"', '"27017:27017"'):
        assert leaked not in prod, f"{leaked} would expose an internal service on the VM"


def test_prod_pulls_pinned_ghcr_images_and_never_builds(prod):
    # R5.2: the VM pulls the exact image CI built and pushed. A `build:` here would compile on the
    # VM and deploy code that CI never tested — the image under test must be the image that runs.
    assert "build:" not in prod, "the prod stack must PULL from GHCR, never build on the VM"
    for image in ("work-smarter-web", "work-smarter-ai"):
        assert f"ghcr.io/${{IMAGE_OWNER:?set IMAGE_OWNER}}/{image}:${{IMAGE_TAG:-latest}}" in prod, \
            f"{image} must come from GHCR pinned to IMAGE_TAG (the deployed commit)"


def test_prod_web_marks_the_session_cookie_secure(prod):
    # prod is HTTPS-only; a session cookie without Secure can leak over an accidental downgrade.
    assert "SESSION_COOKIE_SECURE: ${SESSION_COOKIE_SECURE:-1}" in prod, \
        "prod must default SESSION_COOKIE_SECURE to 1"


def test_prod_services_all_self_heal(prod):
    # caddy + web + ai + db: a crash or a VM reboot must bring the stack back on its own (R5.4).
    assert prod.count("restart: unless-stopped") == 4, "every prod service needs restart: unless-stopped"


def test_prod_web_worker_count_is_env_tunable(prod):
    # #324: the web worker count must stay env-tunable (WEB_WORKERS) so the SAME GHCR image scales onto a
    # bigger VM with one .env line — no rebuild. Default 1 keeps today's behaviour exactly; a hardcoded
    # "--workers", "1" would silently drop the knob. (Raising it loosens the per-process memory:// rate
    # caps N× — see the compose comment; that trade-off is an ops note, not this test's concern.)
    assert '"--workers", "${WEB_WORKERS:-1}"' in prod, \
        "prod web must size gunicorn workers via ${WEB_WORKERS:-1} so the image scales without a rebuild"
    # #324 threads: 16 is the measured knee (8->16 = +56% throughput under load; 16->32 flat). Tunable so a
    # bigger VM can raise it; 1 worker x threads uses the cores (scrypt releases the GIL) and keeps caps exact.
    assert '"--threads", "${WEB_THREADS:-16}"' in prod, \
        "prod web must size gunicorn threads via ${WEB_THREADS:-16} (the measured knee) and stay tunable"


def _web_gunicorn_command(compose_filename):
    """The web service's gunicorn `command:` line from a compose file (uniquely `wsgi:app` + `gthread` —
    the ai/scale commands use `app:create_app()`), or None. Used to prove dev and prod run the same web."""
    for line in (ROOT / compose_filename).read_text().splitlines():
        s = line.strip()
        if s.startswith("command:") and "wsgi:app" in s and "gthread" in s:
            return s
    return None


def test_dev_and_prod_web_run_the_same_gunicorn_command():
    # #324 (mirror): what you run locally must be what deploys to the VM — a divergent worker/thread sizing
    # is exactly why Elad's dev-stack stress numbers (2×4) didn't describe prod (1×8). Both compose files must
    # carry the IDENTICAL, WEB_WORKERS-tunable web command so local mirrors the VM and can't silently drift.
    dev = _web_gunicorn_command("docker-compose.yml")
    prod = _web_gunicorn_command("docker-compose.prod.yml")
    assert dev is not None, "dev docker-compose.yml must define the web gunicorn command (mirror prod)"
    assert prod is not None, "prod docker-compose.prod.yml must define the web gunicorn command"
    assert dev == prod, ("local must mirror the VM — dev and prod web gunicorn commands must be identical.\n"
                         f"  dev : {dev}\n  prod: {prod}")


@pytest.mark.parametrize("compose_filename", ["docker-compose.yml", "docker-compose.prod.yml"])
def test_raising_web_workers_without_shared_limiter_storage_cannot_ship(compose_filename):
    """STRESS_REPORT §4 rec #2, made executable.

    `web/ratelimit.py` stores counters in `memory://` — per **process**. At one gunicorn worker the
    advertised caps (5/min register, 20/min login, the forum + media caps) are exact. Raise
    `WEB_WORKERS` to N and every cap silently becomes N× looser, because each worker counts alone:
    the login brute-force cap the Security suite proves at 20/min would really be 80/min at 4 workers.
    Nothing would go red — the caps still *exist*, they are just wrong, which is the worst shape a
    security control can fail in.

    The fix is not redis. On a 4-vCPU VM, `web` is I/O-bound and threads already use every core
    (scrypt releases the GIL — #330 measured +workers ≈ 0 gain), so a shared store would buy a fourth
    container and a new failure mode to support a knob we have no reason to turn. Instead the
    dependency is pinned here: the shipped default may only exceed one worker if the same file
    configures shared limiter storage. Whoever raises the knob gets a red test naming the trade,
    rather than discovering it from a rate-limit bypass in production.
    """
    command = _web_gunicorn_command(compose_filename)
    assert command is not None, f"{compose_filename} must define the web gunicorn command"

    match = re.search(r'"--workers",\s*"\$\{WEB_WORKERS:-(\d+)\}"', command)
    assert match, (f"{compose_filename}: web must size workers via a ${{WEB_WORKERS:-N}} default so this "
                   f"guard can read it — got: {command}")
    default_workers = int(match.group(1))

    text = (ROOT / compose_filename).read_text()
    shared_storage = "RATELIMIT_STORAGE_URI" in text and "memory://" not in text

    assert default_workers == 1 or shared_storage, (
        f"{compose_filename} defaults web to {default_workers} gunicorn workers while flask-limiter "
        f"still uses per-process memory:// storage, so every advertised rate limit is really "
        f"{default_workers}x looser than the Security suite asserts. Either keep the default at 1 "
        f"worker (scale with --threads, which shares one process) or set RATELIMIT_STORAGE_URI to a "
        f"shared backend in this file."
    )


def test_the_scale_override_is_the_documented_exception_to_the_worker_rule():
    """`docker-compose.scale.yml` deliberately defaults web to 4 workers — it exists to measure the
    horizontal axis, and its runs drive `ai` directly. It is therefore the one file the guard above
    does not cover, and that exemption is only safe while it stays a **benchmark** override: it must
    never be one of the files a deploy uses. Assert exactly that, so the exception cannot quietly
    grow into a shipping configuration."""
    scale = (ROOT / "docker-compose.scale.yml").read_text()
    assert "${WEB_WORKERS:-4}" in scale, "the scale override is expected to raise web workers (the point of it)"

    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert "docker-compose.scale.yml" not in workflow, \
        "the scale override is a benchmark file — CI must never build or deploy with it"
    for shipped in ("docker-compose.prod.yml", "tests/Dockerfile"):
        assert "docker-compose.scale.yml" not in (ROOT / shipped).read_text(), \
            f"{shipped} must not pull in the benchmark-only scale override"


# --------------------------------------------------------------------------- test stack (the runner)

def test_test_stack_defines_a_test_runner(test_stack):
    assert "tests:" in test_stack, "docker-compose.test.yml must define the `tests` runner service"
    assert "dockerfile: tests/Dockerfile" in test_stack, "the runner builds from tests/Dockerfile"
    assert (ROOT / "tests" / "Dockerfile").is_file(), "tests/Dockerfile is missing"


def test_test_runner_image_carries_every_path_its_suites_load_off_disk():
    """The runner's suites exec source files by path (`web/services/db.py`, `db/seed.py`). Those dirs
    must be COPYd into the image, or the suite dies with FileNotFoundError *inside the container* —
    a failure the host's in-process pytest can never reproduce (it reads them straight from the repo).
    """
    dockerfile = _strip_comments((ROOT / "tests" / "Dockerfile").read_text())
    for needed in ("web/", "db/", "tests/"):
        assert f"COPY {needed}" in dockerfile, f"the runner image must COPY {needed} (a suite loads it by path)"


def test_test_runner_drives_the_live_stack_not_the_in_process_app(test_stack):
    # E2E_BASE_URL un-skips tests/System_Tests; TEST_MONGO_URI un-skips the real-Mongo data-layer suite.
    assert "E2E_BASE_URL: http://web:5000" in test_stack, "the runner must target the live web container"
    assert "TEST_MONGO_URI: mongodb://db:27017/worksmarter_test" in test_stack, \
        "the runner must target the throwaway Mongo database"


def test_test_stack_uses_a_throwaway_database(test_stack):
    # a test run must never write to the dev/prod `worksmarter` database.
    assert "mongodb://db:27017/worksmarter_test" in test_stack
    assert "mongodb://db:27017/worksmarter\n" not in test_stack, "the test stack must not use the real DB"


def test_test_runner_publishes_nothing_and_runs_once(test_stack):
    assert "ports:" not in test_stack, "the test override must not publish a new host port"
    assert 'restart: "no"' in test_stack, "the runner is one-shot: it must not be restarted on exit"


def test_test_stack_forces_testing_mode(test_stack):
    assert 'TESTING: "1"' in test_stack, "the test stack must run the app in TESTING mode"


# --------------------------------------------------------------------------- the CI/CD pipeline shape

def test_tests_gate_the_image_build(ci):
    # R2.2: a red test run must never produce a pushed image. The build additionally waits on the
    # cross-container compose run, so a broken web<->ai<->db wire path can't reach GHCR either.
    assert "needs: [checks, compose-e2e]" in ci, \
        "the build job must depend on BOTH the unit/integration gate and the cross-container run"


def test_the_build_gates_the_deploy(ci):
    assert "needs: build" in ci, "the deploy job must depend on a successful build & push"


def test_deploy_only_runs_on_a_green_main_push_behind_the_switch(ci):
    # A pull request must never deploy (R1.3), and the deploy stays dormant until DEPLOY_ENABLED=true.
    assert "github.event_name == 'push' && github.ref == 'refs/heads/main'" in ci
    assert "vars.DEPLOY_ENABLED == 'true'" in ci, "the deploy on/off switch must gate the job"
    assert "vars.SSH_HOST != ''" in ci, "the deploy must stay dormant until the VM host is configured"


def test_the_deploy_verifies_readiness_and_can_roll_back(ci):
    # /ready pings Mongo, so a green health check proves the WHOLE stack serves (R7); a red one must
    # restore the previous image (R8.2) while still failing the run (R8.1).
    assert 'curl --fail --retry 15 --retry-delay 5 --retry-all-errors "https://$SITE/ready"' in ci, \
        "the post-deploy check must hit /ready over HTTPS and fail the job on any error"
    assert "if: failure() && steps.deploy.outputs.prev != ''" in ci, \
        "the auto-rollback step must fire only on a failed deploy that has a previous SHA"
    assert "IMAGE_TAG=${GITHUB_SHA::7}" in ci, "the deploy must pin the exact commit CI built"


def test_the_stress_job_stays_out_of_the_merge_gate(ci):
    # locust needs a live stack and minutes of runtime — it is a manual job, not a per-PR gate.
    assert "workflow_dispatch:" in ci, "the on-demand stress job needs a workflow_dispatch trigger"
    assert "github.event_name == 'workflow_dispatch'" in ci, "the stress job must be manual-only"


def test_the_compose_run_uses_the_test_stack_and_the_runner_exit_code(ci):
    # the job must FAIL when the runner fails; without --exit-code-from it would pass regardless.
    assert "-f docker-compose.yml -f docker-compose.test.yml" in ci
    assert "--exit-code-from tests" in ci, "the compose job must inherit the test-runner's exit code"


# --------------------------------------------------------------------------- media storage

def test_media_bytes_live_on_a_volume_mounted_by_web_alone():
    # attachments are written by the web container only; ai/db must never see them. If the mount is
    # dropped, uploads silently land in the container layer and vanish on the next deploy.
    compose = (ROOT / "docker-compose.yml").read_text()
    assert compose.count("- media-data:/app/media") == 1, "exactly one service (web) mounts media-data"
    # ...and the mount must resolve to a declared named volume, not an implicit host path.
    assert compose.count("media-data") == 2, "media-data must be mounted once and declared once (named volume)"


def test_prod_media_bytes_persist_on_the_same_web_volume(prod):
    # The check above guarded only the BASE compose — so when the prod stack diverged (the media volume
    # was never added to docker-compose.prod.yml), attachment bytes lived in web's ephemeral layer and
    # vanished on every redeploy (the Mongo `media` records survived but pointed at 404s). That gap
    # shipped a whole release before a live redeploy surfaced it. This closes the blind spot: PROD must
    # mount AND declare the same named volume, so persistence holds on the deployed stack too.
    assert prod.count("- media-data:/app/media") == 1, "prod web must mount media-data (else uploads are ephemeral)"
    assert prod.count("media-data") == 2, "prod must MOUNT and DECLARE the media-data named volume"


def test_the_ai_container_logs_the_requests_it_serves():
    """`ai` served every /predict silently: gunicorn's access log is OFF by default, and ai/app.py logs
    only the failure paths (shed, timeout, dead worker, raising job). A SUCCESSFUL prediction therefore
    left no trace on the container that made it — so when web reports a degraded prediction there is
    nothing to correlate against, and with `--scale ai=N` no way to tell which replica served it (#546).
    Asserted here rather than trusted, because this is exactly how #539's scaling profile silently lost
    `wsgi:app` and its logging: a dropped flag changes nothing visible until you need the logs.
    """
    dockerfile = _strip_comments((ROOT / "ai" / "Dockerfile").read_text())
    assert "--access-logfile" in dockerfile and "--error-logfile" in dockerfile, \
        "ai's gunicorn must log requests + errors, or the container is silent about its traffic"
    assert '"--access-logfile", "-"' in dockerfile and '"--error-logfile", "-"' in dockerfile, \
        "both logs must go to stdout/stderr so `docker logs ai` (and the VM's journal) carry them"


def test_every_prod_service_bounds_its_logs(prod):
    """Docker's json-file driver keeps EVERY line forever unless told otherwise, and the prod stack logs
    a request per healthcheck at `interval: 10s` on two containers — ~8.6k lines per container per day of
    pure heartbeat, on the same 1 GB VM disk Mongo writes to (#547). The failure mode isn't a crash; it's
    Mongo failing writes on a full disk weeks later. Uploads are capped (MEDIA_MAX_TOTAL_BYTES, #313); the
    logs recording those caps were not. Asserted per service so a service added later can't ship unbounded.
    """
    services = [name for name in ("caddy", "web", "ai", "db") if f"\n  {name}:" in prod]
    assert len(services) == 4, "prod must define caddy/web/ai/db — update this test if that changes"
    assert prod.count("max-size:") >= 1 and prod.count("max-file:") >= 1, \
        "prod must bound the json-file log driver (max-size + max-file)"
    # Anchored or repeated, every service has to END UP with the option — compose resolves both the same
    # way, so assert on the merged config rather than on how it was written.
    merged = subprocess.run(["docker", "compose", "-f", str(ROOT / "docker-compose.prod.yml"), "config", "--format", "json"],
                            capture_output=True, text=True, cwd=str(ROOT),
                            env={**os.environ, "IMAGE_OWNER": "x", "SECRET_KEY": "x", "SITE_ADDRESS": "localhost"})
    if merged.returncode != 0:
        pytest.skip("docker compose not available to resolve the merged prod config")
    for name, svc in json.loads(merged.stdout)["services"].items():
        opts = (svc.get("logging") or {}).get("options") or {}
        assert opts.get("max-size"), f"{name} must cap its log file size"
        assert opts.get("max-file"), f"{name} must cap how many rotated log files it keeps"


def test_every_env_knob_the_app_reads_is_documented_in_env_example():
    """`.env.example` is the only thing a deployer reads before setting up a stack — an undocumented
    knob is one nobody knows to set, and two of them are anti-abuse switches (RATELIMIT_ENABLED,
    MEDIA_ALLOWED_MIME). Drift is invisible until someone needs the knob in production, so it is
    asserted: found 4 undocumented at the time this test was written, all of them shipped months earlier.

    Scoped to `web/config.py` because that is the file whose defaults `.env.example` mirrors. TESTING and
    FLASK_DEBUG are excluded on purpose: they are harness switches, not deployment configuration.
    """
    config = (ROOT / "web" / "config.py").read_text(encoding="utf-8")
    read = set(re.findall(r'environ\.get\(\s*"([A-Z0-9_]+)"', config))
    read |= set(re.findall(r'_env\w*\(\s*"([A-Z0-9_]+)"', config))
    read -= {"TESTING", "FLASK_DEBUG"}
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    undocumented = sorted(k for k in read if k not in example)
    assert not undocumented, f".env.example does not mention: {undocumented}"


def test_prod_backups_survive_the_container_that_wrote_them(prod):
    """`db/backup.sh` has to run INSIDE the db container — mongodump ships in the mongo image and the VM
    host has no MongoDB tools installed (measured: `/usr/bin/mongodump` in db, MISSING in web). An archive
    written to a container path therefore dies with that container, and the next deploy recreates it (#550).
    A host-side bind mount is what makes a backup a backup rather than a file with a countdown on it.
    """
    assert "- ./backups:/backups" in prod, \
        "prod db must bind-mount a host directory for backup archives (a container path dies with the container)"


def test_ai_logs_its_requests_wherever_its_command_is_overridden(prod):
    """#546 put the log flags in `ai/Dockerfile`, and prod overrides `command:` — which REPLACES the
    image CMD, so prod shipped without them and its container stayed silent. Exactly the shape of #539,
    where the scaling profile replaced web's command and silently dropped `wsgi:app`. Assert the
    effective command, not the image default.
    """
    ai_block = prod[prod.index("\n  ai:"):]
    command = ai_block[ai_block.index("command:"):].splitlines()[0]
    assert "--access-logfile" in command and "--error-logfile" in command, \
        "prod's ai command overrides the image CMD, so it must repeat the log flags"


def test_the_ai_healthcheck_can_see_a_wedged_queue(prod, dev_stack):
    """A dead pool worker left `/health` answering 200 while every prediction hung behind a lock that
    was never released, so Docker reported the container healthy and never restarted it (#555). The
    probe has to touch the queue itself: `/queue/stats` takes the queue's own lock, so it goes red
    exactly when the queue is stuck — which is the only signal that reaches Docker's restart policy.
    """
    for name, stack in (("prod", prod), ("dev", dev_stack)):
        ai_block = stack[stack.index("\n  ai:"):]
        healthcheck = ai_block[ai_block.index("healthcheck:"):]
        probe = healthcheck[:healthcheck.index("interval:")]
        assert "/queue/stats" in probe, f"{name}: ai's healthcheck must exercise the queue, not just /health"
