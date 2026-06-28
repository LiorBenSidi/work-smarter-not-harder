"""Gunicorn entrypoint for the web container. OWNER: Lior.

Configuring logging here (not in ``create_app``) keeps the app factory side-effect-free for tests,
while the real process gets console + rotating-file logging the moment a worker boots. Run by the
Dockerfile: ``gunicorn ... wsgi:app``.
"""
from app import create_app
from logging_config import configure_logging

configure_logging()        # reads ENABLE_LOGGING / LOG_LEVEL / LOG_FILE from the environment
app = create_app()
