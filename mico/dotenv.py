"""Minimal .env loader for mico configuration.

Only recognizes MICO_API_KEY, MICO_BASE_URL, MICO_MODEL.
System environment variables take precedence over .env values.
"""

import os
from pathlib import Path

_ENV_KEYS = {"MICO_API_KEY", "MICO_BASE_URL", "MICO_MODEL"}


def _strip_quotes(value: str) -> str:
    """Strip matching single or double quotes from a value."""
    if len(value) >= 2 and (
        (value[0] == '"' and value[-1] == '"')
        or (value[0] == "'" and value[-1] == "'")
    ):
        return value[1:-1]
    return value


def parse_dotenv(path: str | Path) -> dict[str, str]:
    """Parse a .env file and return recognized key-value pairs.

    Supports: empty lines, # comments, KEY=value, export KEY=value,
    single/double quoted values. Only keys in _ENV_KEYS are returned.
    """
    path = Path(path)
    result: dict[str, str] = {}
    if not path.is_file():
        return result

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Strip optional 'export ' prefix
        if line.startswith("export "):
            line = line[len("export "):]
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key not in _ENV_KEYS:
            continue
        value = _strip_quotes(value.strip())
        result[key] = value

    return result


def load_dotenv(cwd: str | Path) -> dict[str, str]:
    """Load .env from *cwd* into os.environ for keys not already set.

    Returns the dict of newly-set values (keys absent from the original
    system environment). System env vars are never overridden.
    """
    cwd = Path(cwd)
    raw = parse_dotenv(cwd / ".env")
    injected: dict[str, str] = {}
    for k, v in raw.items():
        if k not in os.environ:
            os.environ[k] = v
            injected[k] = v
    return injected
