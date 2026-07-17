"""Audit every pinned PyPI version in the repo against the GitHub Advisory DB (#335). OWNER: Lior.

Answers one question for each pin: *does the version we actually ship carry a known CVE?* It
resolves each advisory's ``vulnerable_version_range`` and tests the pinned version against it with
``packaging`` -- exact matching, not an eyeballed range.

Two properties matter more than the report itself:

* **A failed lookup is never reported as clean.** A registry error yields UNKNOWN and a non-zero
  exit, because a silent "no CVEs found" is indistinguishable from a working query that found none.
* **A known-vulnerable control runs first.** If the control comes back clean the query itself is
  broken, so the run aborts rather than issue a false all-clear. (A malformed filter did exactly
  this during the manual audit that motivated #335 -- empty output looked like good news.)

Usage:
    python scripts/audit_dependencies.py

    GITHUB_TOKEN=<tok> python scripts/audit_dependencies.py   # optional: 5000 req/h instead of 60

Exit codes:  0 = every pin clean   1 = at least one pin vulnerable   2 = audit could not be trusted
Requires ``requests`` + ``packaging`` (both already present via web/requirements.txt and pytest).
"""
import logging
import os
import re
import sys
from pathlib import Path

import requests
from packaging.specifiers import SpecifierSet
from packaging.version import InvalidVersion, Version

logger = logging.getLogger("audit_dependencies")

ROOT = Path(__file__).resolve().parent.parent
MANIFESTS = ["web/requirements.txt", "ai/requirements.txt", "tests/requirements.txt", "requirements-dev.txt"]

API = "https://api.github.com/advisories"
TIMEOUT = 20
PIN_RE = re.compile(r"^\s*([A-Za-z0-9._-]+)\s*==\s*([A-Za-z0-9._-]+)")

# A package + version with advisories that will never be retracted -- if this comes back clean, the
# query is broken, not the world.
CONTROL = ("django", "3.0.0")

_cache = {}


def _session():
    s = requests.Session()
    s.headers["Accept"] = "application/vnd.github+json"
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        s.headers["Authorization"] = f"Bearer {token}"
    return s


def advisories(session, package):
    """Every pip advisory affecting ``package``. Returns None when the lookup itself failed."""
    key = package.lower()
    if key not in _cache:
        try:
            r = session.get(API, params={"ecosystem": "pip", "affects": package, "per_page": 100}, timeout=TIMEOUT)
            r.raise_for_status()
            _cache[key] = r.json()
        except (requests.RequestException, ValueError) as exc:
            logger.error("  lookup FAILED for %s: %s", package, exc)
            _cache[key] = None                      # None == unknown, never an implicit "clean"
    return _cache[key]


def _normalise(spec):
    """GitHub writes ranges loosely: '>= 2.3.0, < 2.31.0' -> '>=2.3.0,<2.31.0'; '= 3.1.0' -> '==3.1.0'."""
    return re.sub(r"(?<![<>=!~])=(?![=])", "==", spec.replace(" ", ""))


def vulnerabilities(session, package, version):
    """Advisories whose vulnerable range genuinely contains ``version``. None => lookup failed."""
    found = advisories(session, package)
    if found is None:
        return None
    hits = []
    for advisory in found:
        for vuln in advisory.get("vulnerabilities") or []:
            if (vuln.get("package") or {}).get("name", "").lower() != package.lower():
                continue
            rng = vuln.get("vulnerable_version_range")
            if not rng:
                continue
            try:
                affected = Version(version) in SpecifierSet(_normalise(rng))
            except (InvalidVersion, ValueError) as exc:
                logger.error("  unparseable range for %s (%r): %s -- treating as UNKNOWN", package, rng, exc)
                return None
            if affected:
                patched = vuln.get("first_patched_version")
                hits.append({
                    "ghsa": advisory.get("ghsa_id"),
                    "cve": advisory.get("cve_id") or "-",
                    "severity": advisory.get("severity"),
                    "range": rng,
                    "patched": patched.get("identifier") if isinstance(patched, dict) else (patched or "none"),
                })
    return hits


def pinned(manifest):
    """[(package, version)] for every '==' pin in the manifest. Comments and loose pins are ignored."""
    path = ROOT / manifest
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        if line.lstrip().startswith("#"):
            continue
        m = PIN_RE.match(line)
        if m:
            out.append((m.group(1), m.group(2)))
    return out


def audit():
    """Returns (vulnerable_count, unknown_count). Logs a per-package report as it goes."""
    session = _session()

    control_pkg, control_ver = CONTROL
    control = vulnerabilities(session, control_pkg, control_ver)
    if not control:
        logger.error("CONTROL FAILED: %s==%s reported no advisories. The query is broken, so every "
                     "'clean' below would be meaningless. Aborting.", control_pkg, control_ver)
        sys.exit(2)
    logger.info("control ok: %s==%s matched %d advisories\n", control_pkg, control_ver, len(control))

    vulnerable = unknown = 0
    for manifest in MANIFESTS:
        pins = pinned(manifest)
        if not pins:
            continue
        logger.info("%s", manifest)
        for package, version in pins:
            hits = vulnerabilities(session, package, version)
            if hits is None:
                unknown += 1
                logger.warning("  ?? %s==%s  UNKNOWN (lookup failed)", package, version)
            elif hits:
                vulnerable += len(hits)
                logger.warning("  XX %s==%s  %d vulnerable", package, version, len(hits))
                for h in hits:
                    logger.warning("       [%s] %s %s :: '%s' -> patched %s",
                                   h["severity"], h["ghsa"], h["cve"], h["range"], h["patched"])
            else:
                logger.info("  ok %s==%s", package, version)
        logger.info("")
    return vulnerable, unknown


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    vuln, unk = audit()
    logger.info("%d advisories match a current pin; %d unknown", vuln, unk)
    sys.exit(2 if unk else (1 if vuln else 0))
