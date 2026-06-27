"""Env-driven config — no secrets in code (real values come from .env; see .env.example)."""
import os


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "")          # required in real runs (set via .env)
    MONGO_URI = os.environ.get("MONGO_URI", "mongodb://db:27017/worksmarter")
    AI_URL = os.environ.get("AI_URL", "http://ai:5000")
    DEBUG = os.environ.get("FLASK_DEBUG", "0") == "1"
    TESTING = os.environ.get("TESTING", "0") == "1"
