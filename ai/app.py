"""AI decision engine (internal container). OWNER: Lior.

CONTRACT (don't change without updating docs/DESIGN.md + telling the team):
    POST /predict  {features: {...}} -> {state: <category>, proba: {...}, recommendations: {...}}

The trained model is baked into the image (see Dockerfile); this stub returns a 501 placeholder
that already honours the response shape. Implement the model + recommendation engine behind it.
PMData notes + the open decisions (binning, augmentation, ...) live in ai/README.md.
"""
import logging

from flask import Flask, jsonify, request

logger = logging.getLogger(__name__)


def create_app():
    app = Flask(__name__)

    @app.get("/health")
    def health():
        return jsonify(status="ok", service="ai")

    @app.post("/predict")
    def predict():
        features = (request.get_json(silent=True) or {}).get("features", {})
        logger.info("predict called with %d feature(s) (placeholder)", len(features))
        # OWNER (Lior): replace this placeholder with the baked Random Forest + recommendation engine.
        # KEEP the response shape (the web->ai contract). PMData notes + decisions: ai/README.md.
        return jsonify(
            state="Moderate",
            proba={"Moderate": 1.0},
            recommendations=[],
            placeholder=True,
        )

    return app
