"""Train the readiness model -> model/model.pkl (baked into the image). OWNER: Lior.

Plan (your way — see ../README.md): load PMData (wellness.csv + srpe.csv), merge per participant
by date, bin readiness 0-10 into classes, train a Random Forest, then joblib.dump('model.pkl').
Pin scikit-learn in ../requirements.txt to the version you train with so the pickle loads in the image.
Keep the raw dataset OUT of the repo — bake only the trained model.
"""
# OWNER (Lior): implement. This placeholder intentionally does nothing yet.
