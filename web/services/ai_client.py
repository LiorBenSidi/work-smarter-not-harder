"""Client for the internal AI container (`POST {AI_URL}/predict`). OWNER: Lior (web).

Baseline glue so routes can call the AI today. Fault tolerance (mandatory — docs/DESIGN.md §5):
on AI failure this returns ``None`` and the caller degrades gracefully — the app must NOT crash.
"""
import logging

import requests

logger = logging.getLogger(__name__)


def build_features(profile, metrics, **extra):
    """Assemble the ``/predict`` ``features`` body from a stored profile plus today's metrics.

    One builder, not three: ``/checkin``, the recommendations regen and ``/dashboard`` all send the
    same payload, and the last time a fix landed at one call site but not its siblings it took three
    issues to spot (#327 -> #449 -> #453). Adding a field here reaches every caller at once.

    ``training_program`` is a PROFILE field -- weekly sets per muscle group, PROPOSAL-v2 §3's
    Advanced-tier input (#566). The ai side reads the same data under a different name and a
    different shape: ``features["performed"]``, a flat list of ``{"muscle_group", "sets"}``
    (docs/PERFORMED_VOLUME_SPEC.md). Translating here keeps that wire detail at the seam that owns
    the contract, instead of leaking ai/'s vocabulary into the profile schema or the form.

    A profile with no ``training_program`` (every profile saved before #566) simply carries no
    ``performed`` key, which the analysis treats as "nothing to say" -- the same graceful degradation
    every other optional input already has.
    """
    features = {**(profile or {}), **(metrics or {}), **extra}
    program = features.pop("training_program", None)
    if program:
        features["performed"] = [{"muscle_group": group, "sets": sets}
                                 for group, sets in program.items()]
    return features


def predict(ai_url, features, timeout=30):
    """POST `features` to `{ai_url}/predict`; return the parsed JSON, or None if the AI is unavailable.

    `timeout` must be >= the ai queue's AI_PREDICT_TIMEOUT_SECONDS, or web gives up on a result ai is
    still computing (discarding the work while the worker stays busy). Callers pass the configured
    value (`AI_CLIENT_TIMEOUT`); the 30 default is a safe floor matching the ai queue's default.
    """
    try:
        resp = requests.post(f"{ai_url}/predict", json={"features": features}, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except (requests.RequestException, ValueError):
        # network/HTTP failure OR a 200 with a non-JSON body -> degrade gracefully (DESIGN §5)
        logger.warning("ai /predict unavailable or returned bad JSON — degrading gracefully", exc_info=True)
        return None
