"""Client for the internal AI container (`POST {AI_URL}/predict`). OWNER: Lior (web).

Baseline glue so routes can call the AI today. Fault tolerance (mandatory — docs/DESIGN.md §5):
on AI failure this returns ``None`` and the caller degrades gracefully — the app must NOT crash.
"""
import logging

import requests

logger = logging.getLogger(__name__)


def predict(ai_url, features, timeout=5):
    """POST `features` to `{ai_url}/predict`; return the parsed JSON, or None if the AI is unavailable."""
    try:
        resp = requests.post(f"{ai_url}/predict", json={"features": features}, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except (requests.RequestException, ValueError):
        # network/HTTP failure OR a 200 with a non-JSON body -> degrade gracefully (DESIGN §5)
        logger.warning("ai /predict unavailable or returned bad JSON — degrading gracefully", exc_info=True)
        return None
