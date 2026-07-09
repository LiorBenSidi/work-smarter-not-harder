"""The model seam — the single function the job queue works in parallel.

OWNER of the *body*: Shiri (the Random Forest + recommendation engine).
OWNER of the *signature*: Elad (the queue calls it from a worker process).

`predict_one` is deliberately a module-level function: `ProcessPoolExecutor` pickles it by
qualified name, so it must stay importable as `inference.predict_one` and must not close over
app/request state. Load the baked model once at import time (module scope) so each worker process
pays for it exactly once, not per request.

CONTRACT (the `web -> ai` response shape — see docs/DESIGN.md):
    predict_one({...features...}) -> {"state": str, "proba": {str: float}, "recommendations": [...]}
"""
import logging

logger = logging.getLogger(__name__)


def predict_one(features):
    """Score one feature vector. Pure, CPU-bound, no I/O — safe to run in a worker process."""
    logger.info("predict called with %d feature(s) (placeholder)", len(features))
    # OWNER (Shiri): replace this placeholder with the baked Random Forest + recommendation engine.
    # KEEP the returned keys (the web->ai contract). PMData notes + decisions: ai/README.md.
    return {
        "state": "Moderate",
        "proba": {"Moderate": 1.0},
        "recommendations": [],
        "placeholder": True,
    }
