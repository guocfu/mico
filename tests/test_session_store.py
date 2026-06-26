import json
from pathlib import Path

from mico.session_store import SessionStore


def test_load_nonexistent_session_returns_none(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    result = store.load("default")
    assert result is None


def test_save_then_load_roundtrip(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    data = {"session_id": "default", "memory": {"task_summary": "hello"}}
    store.save("default", data)
    loaded = store.load("default")
    assert loaded["session_id"] == "default"
    assert loaded["memory"]["task_summary"] == "hello"


def test_save_uses_atomic_write(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    data = {"session_id": "default", "memory": {}}
    store.save("default", data)
    path = tmp_path / "sessions" / "default.json"
    assert path.exists()
    tmp_file = path.with_suffix(".json.tmp")
    assert not tmp_file.exists()



def test_load_corrupted_json_returns_none(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir(parents=True)
    (sessions_dir / "default.json").write_text("not valid json{{", encoding="utf-8")
    result = store.load("default")
    assert result is None


def test_load_empty_file_returns_none(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir(parents=True)
    (sessions_dir / "default.json").write_text("", encoding="utf-8")
    result = store.load("default")
    assert result is None



def test_save_creates_parent_directories(tmp_path):
    store = SessionStore(tmp_path / "deep" / "nested" / "sessions")
    data = {"session_id": "default"}
    store.save("default", data)
    loaded = store.load("default")
    assert loaded is not None
    assert loaded["session_id"] == "default"


def test_load_non_dict_json_returns_none(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir(parents=True)
    (sessions_dir / "default.json").write_text(json.dumps("just a string"), encoding="utf-8")
    result = store.load("default")
    assert result is None



def test_overwrite_existing_session(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    store.save("default", {"v": 1})
    store.save("default", {"v": 2})
    loaded = store.load("default")
    assert loaded["v"] == 2


# --- last_error tests ---


def test_load_missing_file_last_error_is_none(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    result = store.load("default")
    assert result is None
    assert store.last_error is None


def test_load_corrupted_json_sets_last_error(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir(parents=True)
    (sessions_dir / "default.json").write_text("not valid json{{", encoding="utf-8")
    result = store.load("default")
    assert result is None
    assert store.last_error == "json_error"


def test_load_empty_file_sets_last_error(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir(parents=True)
    (sessions_dir / "default.json").write_text("", encoding="utf-8")
    result = store.load("default")
    assert result is None
    assert store.last_error == "empty_file"


def test_load_whitespace_only_file_sets_last_error(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir(parents=True)
    (sessions_dir / "default.json").write_text("   \n\t  ", encoding="utf-8")
    result = store.load("default")
    assert result is None
    assert store.last_error == "empty_file"


def test_load_non_dict_json_sets_last_error(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir(parents=True)
    (sessions_dir / "default.json").write_text(json.dumps("just a string"), encoding="utf-8")
    result = store.load("default")
    assert result is None
    assert store.last_error == "schema_error"


def test_load_list_json_sets_last_error(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir(parents=True)
    (sessions_dir / "default.json").write_text("[1, 2, 3]", encoding="utf-8")
    result = store.load("default")
    assert result is None
    assert store.last_error == "schema_error"


def test_load_successful_clears_last_error(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir(parents=True)
    (sessions_dir / "default.json").write_text("not json{{", encoding="utf-8")
    store.load("default")
    assert store.last_error == "json_error"

    store.save("default", {"ok": True})
    result = store.load("default")
    assert result == {"ok": True}
    assert store.last_error is None


def test_load_io_error_sets_last_error(tmp_path, monkeypatch):
    store = SessionStore(tmp_path / "sessions")
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir(parents=True)
    (sessions_dir / "default.json").write_text(json.dumps({"ok": True}), encoding="utf-8")

    original_read_text = Path.read_text

    def mock_read_text(self, *args, **kwargs):
        if self.name == "default.json":
            raise OSError("simulated IO error")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", mock_read_text)
    result = store.load("default")
    assert result is None
    assert store.last_error == "io_error"
