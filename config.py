import os
import secrets
from datetime import timedelta
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent / ".env")


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY")
    if not SECRET_KEY or SECRET_KEY in {"dev-key-change-in-production", "replace-with-a-random-long-secret"}:
        SECRET_KEY = secrets.token_hex(32)
    LOGIN_USERNAME = os.environ.get("LOGIN_USERNAME", "RescueEchague")
    LOGIN_PASSWORD_HASH = os.environ.get("LOGIN_PASSWORD_HASH", 'scrypt:32768:8:1$cNjaiERjonCUfgF2$c9cbe63d019878bb03baca7815084c76f96777fb2181920fc0cd6c7164be198c6d4f879446d274b1e28bbcf87d7c010e99a02c32aa4ee3e8b69dea42742f656e')
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "0") == "1"
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)
    SESSION_REFRESH_EACH_REQUEST = False
    MAX_CONTENT_LENGTH = 32 * 1024 * 1024
    JSON_SORT_KEYS = False
    APP_NAME = "MDRRMC Echague"
    APP_SHORT_NAME = "MDRRMC"
    AGENCY_NOTE = "Traffic safety analytics for Echague, Isabela"
    DASHBOARD_TITLE = "Road Crash Risk & Response Overview"
    PRESCRIPTIONS_PATH = os.environ.get(
        "PRESCRIPTIONS_PATH",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "prescriptions.json"),
    )
