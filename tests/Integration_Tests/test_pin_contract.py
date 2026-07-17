"""Cross-manifest pin contract — OWNER: Lior.

Some packages are pinned in more than one requirements file. Where two manifests name the same
package, they must name the SAME version — and nothing enforced that until this file existed.

Why it matters (this is not theoretical — it cost a morning):

``ci.yml``'s "Install tooling + project deps" step installs EVERY manifest into ONE environment,
web first and ai second. When #317 moved ``web`` to flask 3.1.3 while ``ai`` still pinned 3.1.0,
pip resolved the disagreement the only way it can — by uninstalling the first::

    Attempting uninstall: flask
      Uninstalling Flask-3.1.3:
        Successfully uninstalled Flask-3.1.3
    Successfully installed flask-3.1.0 ...

No error. No resolver warning. ``pip check`` stayed clean, because nothing was *incompatible* —
the second pin simply won. The result was that the whole suite ran against a flask the web
container does not ship, so the version we actually deploy was exercised by nothing except the
container jobs. A silent downgrade is invisible precisely because it succeeds.

These are cheap text assertions on the committed files (no Docker, no network, no live stack), so
they run in the normal per-PR gate and turn the next divergence into a red PR instead of a quiet
loss of test fidelity. Same shape as test_deploy_contract.py's dev/prod compose guards.

Deliberately NOT asserted: that every manifest pins the same set of packages. They are different
services with different needs — ``ai`` has no pymongo, ``web`` has no scikit-learn. The contract is
only "where two files pin the same name, the versions agree".
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

MANIFESTS = ["web/requirements.txt", "ai/requirements.txt", "tests/requirements.txt", "requirements-dev.txt"]
PIN_RE = re.compile(r"^\s*([A-Za-z0-9._-]+)\s*==\s*([A-Za-z0-9._-]+)")


def _pins(manifest):
    """{package_lower: version} for every '==' pin. Comment lines are ignored."""
    out = {}
    for line in (ROOT / manifest).read_text().splitlines():
        if line.lstrip().startswith("#"):
            continue
        m = PIN_RE.match(line)
        if m:
            out[m.group(1).lower()] = m.group(2)
    return out


@pytest.fixture(scope="module")
def pins():
    return {m: _pins(m) for m in MANIFESTS}


def test_every_manifest_is_parseable_and_non_empty(pins):
    """Guard the guard: if the parser silently matched nothing, every test below would vacuously pass."""
    for manifest, found in pins.items():
        assert found, f"{manifest}: no '==' pins parsed — the contract tests below would be meaningless"


def test_web_and_ai_pin_the_same_flask(pins):
    """The exact divergence that silently downgraded CI's flask (#343).

    Both containers run flask, and ci.yml installs both manifests into one environment. If these
    disagree, the suite tests whichever manifest is installed last — not what web deploys.
    """
    web, ai = pins["web/requirements.txt"].get("flask"), pins["ai/requirements.txt"].get("flask")
    assert web and ai, "both web and ai must pin flask explicitly (an unpinned flask floats between builds)"
    assert web == ai, (
        f"flask pins disagree: web={web} ai={ai}. ci.yml installs every manifest into ONE env, so the "
        f"second install silently uninstalls the first and the suite then tests a version we do not ship. "
        f"Move them together, and prefer raising the lower pin — never lower the higher one to match."
    )


def test_dev_and_test_runner_pin_the_same_pytest(pins):
    """requirements-dev.txt documents this invariant; nothing enforced it until now.

    The local pre-push gate and CI install requirements-dev.txt; the cross-container test-runner
    installs tests/requirements.txt. Divergence means the two gates run different pytest majors.
    """
    dev, runner = pins["requirements-dev.txt"].get("pytest"), pins["tests/requirements.txt"].get("pytest")
    assert dev and runner, "both requirements-dev.txt and tests/requirements.txt must pin pytest"
    assert dev == runner, (
        f"pytest pins disagree: requirements-dev.txt={dev} tests/requirements.txt={runner}. Local + CI "
        f"run the former and the test-runner container runs the latter, so they would gate on different "
        f"pytest versions."
    )


def test_shared_packages_agree_across_every_manifest(pins):
    """The general rule the two tests above are instances of.

    Catches a future shared pin nobody thought to write a named test for (requests, pymongo, gunicorn...).
    """
    versions = {}
    for manifest, found in pins.items():
        for package, version in found.items():
            versions.setdefault(package, {})[manifest] = version

    disagreements = {
        package: where for package, where in versions.items()
        if len(where) > 1 and len(set(where.values())) > 1
    }
    assert not disagreements, (
        "a package is pinned to different versions in different manifests:\n" + "\n".join(
            f"  {package}: " + ", ".join(f"{m}={v}" for m, v in sorted(where.items()))
            for package, where in sorted(disagreements.items())
        ) + "\nWhere two manifests pin the same package, the versions must match — see this file's docstring."
    )
