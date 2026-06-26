import json
from pathlib import Path


class SessionStore:
    """Manages session JSON persistence with atomic writes."""

    def __init__(self, root):
        self.root = Path(root)
        self.last_error = None

    def save(self, session_id, data):
        """Atomic write: write to tmp file then replace."""
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / f"{session_id}.json"
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    def load(self, session_id):
        """Load session JSON. Returns None if missing, empty, or corrupted."""
        path = self.root / f"{session_id}.json"
        if not path.exists():
            self.last_error = None
            return None
        try:
            text = path.read_text(encoding="utf-8")
            if not text.strip():
                self.last_error = "empty_file"
                return None
            data = json.loads(text)
            if not isinstance(data, dict):
                self.last_error = "schema_error"
                return None
            self.last_error = None
            return data
        except json.JSONDecodeError:
            self.last_error = "json_error"
            return None
        except OSError:
            self.last_error = "io_error"
            return None
