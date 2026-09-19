"""Load only this demo's configuration; never print secret values."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ALLOWED = {"DAYTONA_API_KEY", "OPENAI_API_KEY", "OPENAI_MODEL"}


def load_env(path=None):
    path = Path(path) if path else ROOT / ".env"
    if not path.exists():
        return
    for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not separator or key not in ALLOWED:
            raise ValueError(f"Unsupported .env entry on line {number}; expected one of {sorted(ALLOWED)}")
        if value[:1] in {"'", '"'}:
            if len(value) < 2 or value[-1] != value[0]:
                raise ValueError(f"Unmatched quotes on .env line {number}")
            value = value[1:-1]
        if value and not os.environ.get(key):
            os.environ[key] = value


def redact(text):
    text = str(text)
    for key in ("DAYTONA_API_KEY", "OPENAI_API_KEY"):
        value = os.environ.get(key)
        if value:
            text = text.replace(value, "[REDACTED]")
    return text
