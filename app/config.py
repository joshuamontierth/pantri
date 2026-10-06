import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR.parent / "data"))
DATABASE_PATH = Path(os.environ.get("DATABASE_PATH", DATA_DIR / "shopping.db"))

# Set COOKIE_SECURE=true when the site is served over HTTPS (e.g. behind a TLS reverse proxy).
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "false").lower() in ("1", "true", "yes")

# Ollama server with a vision model, used to read recipes from photos. Empty OLLAMA_URL turns it off.
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ollama.example.com:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "gemma4:26b-a4b-it-qat")
OLLAMA_TIMEOUT = int(os.environ.get("OLLAMA_TIMEOUT", "300"))
# Ollama's default context (4096 tokens) is too small for four photos, a long catalog and the directions.
OLLAMA_NUM_CTX = int(os.environ.get("OLLAMA_NUM_CTX", "8192"))

SESSION_COOKIE = "session"
SESSION_DAYS = 365
MIN_PASSWORD_LENGTH = 8
