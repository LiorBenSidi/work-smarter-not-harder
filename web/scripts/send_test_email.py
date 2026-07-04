#!/usr/bin/env python3
"""Send ONE test email through the app's configured backend — proves real delivery end to end.

With no ``SMTP_HOST`` set it uses the log backend (writes the message to the log) — always safe to run.
Set ``SMTP_HOST`` / ``SMTP_USER`` / ``SMTP_PASS`` / ``MAIL_FROM`` (see ``.env`` / ``.env.example``) to send
real mail — this is how you verify a provider (e.g. free Brevo) once its SMTP key is in ``.env``.

In the container (reads the compose ``.env``):
    docker compose exec web python scripts/send_test_email.py --to you@example.com
Locally:
    SMTP_HOST=smtp-relay.brevo.com SMTP_USER=... SMTP_PASS=... MAIL_FROM='Work Smarter, Not Harder <you@dom>' \
        python web/scripts/send_test_email.py --to you@example.com

Exit code 0 = handed off / logged, 1 = a configured SMTP send failed (check the creds + a verified sender).
"""
import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # web/ on path for local runs

# Load the repo-root .env BEFORE importing Config (Config reads os.environ at import time). This makes a plain
# `python web/scripts/send_test_email.py --to ...` work on the host with NO `source .env` — which runs the file
# as a shell script and mangles values containing `< >` (e.g. MAIL_FROM="Name <addr>"), silently corrupting the
# sender into a bare display name and getting the send rejected (SMTP 501). python-dotenv parses such values
# correctly and never overrides vars already in the environment, so in the container compose's env still wins.
_ENV_STATUS = "python-dotenv not installed — using the process environment"
try:
    from dotenv import load_dotenv
    _env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".env")
    _ENV_STATUS = f"loaded {_env_path}" if load_dotenv(_env_path) else f"no .env at {_env_path} — using the process environment"
except ImportError:
    pass  # not installed (e.g. inside the container) -> rely on the env compose already injected

from config import Config              # noqa: E402  (after the sys.path + dotenv shim above)
from services.email import send_email  # noqa: E402

logger = logging.getLogger("send_test_email")


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")  # so both our lines + email.py's log show
    logger.info("env: %s", _ENV_STATUS)   # surface WHY (missing .env is the #1 "why isn't SMTP used?" cause)
    parser = argparse.ArgumentParser(description="Send a test email via the app's configured backend.")
    parser.add_argument("--to", default="liortestbase@proton.me", help="recipient address")
    args = parser.parse_args()

    # Build a typed config from the app's Config (bool/int coerced) — NOT os.environ, whose string
    # "0" would read truthy for SMTP_STARTTLS.
    cfg = {k: getattr(Config, k) for k in dir(Config) if k.isupper()}
    backend = f"SMTP ({cfg['SMTP_HOST']})" if cfg.get("SMTP_HOST") else "log backend (no SMTP_HOST set)"
    logger.info("Backend: %s  ->  sending to %s ...", backend, args.to)
    ok = send_email(cfg, args.to, "Work Smarter, Not Harder — test email",
                    "This is a test from Work Smarter, Not Harder.\n\n"
                    "If you received it, real email delivery works — your login codes and "
                    "password-reset links will arrive this way.")
    logger.info("Result: %s", "OK (handed off / logged)" if ok else
                "FAILED — check SMTP_USER/SMTP_PASS and that MAIL_FROM is a verified sender in the provider")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
