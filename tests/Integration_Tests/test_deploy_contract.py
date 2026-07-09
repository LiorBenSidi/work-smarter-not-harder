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
