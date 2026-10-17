import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _load_env_file():
    """Settings from a .env file (see .env.example) when running outside Docker. Real environment variables win.

    ENV_FILE picks another file; ENV_FILE="" skips it (the tests do, so a local .env can't change them).
    """
    path = os.environ.get("ENV_FILE", str(BASE_DIR.parent / ".env"))
    if not path or not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip().removeprefix("export ").strip(), value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            os.environ.setdefault(key, value)


_load_env_file()

DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR.parent / "data"))
DATABASE_PATH = Path(os.environ.get("DATABASE_PATH", DATA_DIR / "pantri.db"))

# Set COOKIE_SECURE=true when the site is served over HTTPS (e.g. behind a TLS reverse proxy).
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "false").lower() in ("1", "true", "yes")

# Ollama server with a vision model, used to read recipes and shopping lists from photos.
# Empty (the default) turns that off; recipe links still import from their structured data.
OLLAMA_URL = os.environ.get("OLLAMA_URL", "")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "gemma4:26b-a4b-it-qat")
OLLAMA_TIMEOUT = int(os.environ.get("OLLAMA_TIMEOUT", "300"))
# Ollama's default context (4096 tokens) is too small for four photos, a long catalog and the directions.
OLLAMA_NUM_CTX = int(os.environ.get("OLLAMA_NUM_CTX", "8192"))

# The household's time zone, for "today" and "this week" on the meal calendar (the server itself may run on UTC).
TIMEZONE = os.environ.get("TIMEZONE", "UTC")

SESSION_COOKIE = "session"
SESSION_DAYS = 365
MIN_PASSWORD_LENGTH = 8
