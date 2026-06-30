import json
import re
from pathlib import Path

_SAFE_SESSION_ID_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*$')


class SessionStore:
    """Manages session JSON persistence with atomic writes."""

    def __init__(self, root):
        self.root = Path(root)
        self.last_error = None

    @staticmethod
    def validate_session_id(session_id):
        """Validate session_id is safe for use as a filename component.

        Raises ValueError if the id is empty, contains path separators,
        path traversal sequences, or other unsafe characters.
        Accepts: default, mysession, feature-1, user.name, a_b.
        """
        if not session_id:
            raise ValueError('session_id must not be empty')
        if session_id in ('.', '..'):
            raise ValueError('session_id must not be "." or ".."')
        if not _SAFE_SESSION_ID_RE.match(session_id):
            raise ValueError(
                'session_id contains unsafe characters: ' + repr(session_id)
            )

    def save(self, session_id, data):
        """Atomic write: write to tmp file then replace."""
        self.validate_session_id(session_id)
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / f"{session_id}.json"
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    def load(self, session_id):
        """Load session JSON. Returns None if missing, empty, or corrupted."""
        self.validate_session_id(session_id)
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

    def latest_id(self):
        """Return the most recently modified session id, or None."""
        if not self.root.exists():
            return None
        files = sorted(self.root.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for f in files:
            sid = f.stem
            try:
                self.validate_session_id(sid)
            except ValueError:
                continue
            if self.load(sid) is not None:
                return sid
        return None
