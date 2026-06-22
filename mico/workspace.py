import os
from pathlib import Path


IGNORED_NAMES = {".git", ".mico", "__pycache__", ".pytest_cache", ".venv", "node_modules"}


def clip(text, limit):
    text = str(text)
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def clip_artifact(value, limit=500):
    if isinstance(value, dict):
        return {k: clip_artifact(v, limit) for k, v in value.items()}
    if isinstance(value, list):
        return [clip_artifact(item, limit) for item in value]
    if isinstance(value, tuple):
        return tuple(clip_artifact(item, limit) for item in value)
    if isinstance(value, str):
        return clip(value, limit)
    return value


class Workspace:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.ignored_names = set(IGNORED_NAMES)

    @classmethod
    def build(cls, cwd="."):
        root = Path(cwd).resolve()
        if not root.exists():
            raise ValueError(f"workspace does not exist: {root}")
        if not root.is_dir():
            raise ValueError(f"workspace is not a directory: {root}")
        return cls(root)

    def path(self, value):
        candidate = (self.root / str(value)).resolve()
        try:
            common = os.path.commonpath([str(self.root), str(candidate)])
        except ValueError:
            raise ValueError(f"path escapes workspace: {value}") from None
        if common != str(self.root):
            raise ValueError(f"path escapes workspace: {value}")
        return candidate

    def relative(self, path):
        return str(Path(path).resolve().relative_to(self.root))
