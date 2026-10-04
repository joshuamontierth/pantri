import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR.parent / "data"))
DATABASE_PATH = Path(os.environ.get("DATABASE_PATH", DATA_DIR / "shopping.db"))

# Set COOKIE_SECURE=true when the site is served over HTTPS (e.g. behind a TLS reverse proxy).
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "false").lower() in ("1", "true", "yes")

SESSION_COOKIE = "session"
SESSION_DAYS = 365
MIN_PASSWORD_LENGTH = 8
