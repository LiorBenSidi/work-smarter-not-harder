"""Client for the internal AI container (`POST {AI_URL}/predict`). OWNER: web side (Shiri/Elad).

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
    except requests.RequestException:
        logger.warning("ai /predict unavailable — degrading gracefully", exc_info=True)
        return None
