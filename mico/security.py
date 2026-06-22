import os
import re

_SENSITIVE_KEYWORDS = frozenset({"API_KEY", "TOKEN", "SECRET", "PASSWORD", "AUTH", "AUTHORIZATION"})


def looks_sensitive_key(name):
    segments = str(name).upper().replace("-", "_").split("_")
    if set(segments) & _SENSITIVE_KEYWORDS:
        return True
    for i in range(len(segments) - 1):
        if segments[i] + "_" + segments[i + 1] in _SENSITIVE_KEYWORDS:
            return True
    return False


def _collect_sensitive_values():
    values = set()
    for key, val in os.environ.items():
        if val and looks_sensitive_key(key):
            values.add(val)
    return values


def _build_redact_pattern():
    sensitive = sorted(_collect_sensitive_values(), key=len, reverse=True)
    if not sensitive:
        return None
    return re.compile("|".join(re.escape(v) for v in sensitive))


def redact_artifact(value, _pattern=None):
    if _pattern is None:
        _pattern = _build_redact_pattern()
    return _redact(value, _pattern)


def _redact(value, pattern):
    if isinstance(value, dict):
        return {k: ("[REDACTED]" if looks_sensitive_key(k) else _redact(v, pattern)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(item, pattern) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact(item, pattern) for item in value)
    if isinstance(value, str) and pattern:
        return pattern.sub("[REDACTED]", value)
    return value
