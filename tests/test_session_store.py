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


# --- Task 5: SessionStore.latest_id ---


def test_latest_id_returns_none_when_empty(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    assert store.latest_id() is None


def test_latest_id_returns_most_recent(tmp_path):
    import time
    store = SessionStore(tmp_path / "sessions")
    store.save("first", {"session_id": "first", "memory": {}})
    time.sleep(0.05)
    store.save("second", {"session_id": "second", "memory": {}})
    assert store.latest_id() == "second"


def test_latest_id_considers_mtime(tmp_path):
    import time
    import os
    store = SessionStore(tmp_path / "sessions")
    store.save("old", {"session_id": "old", "memory": {}})
    time.sleep(0.1)
    store.save("new", {"session_id": "new", "memory": {}})
    # Force old.json to have a newer mtime using os.utime
    old_path = str(tmp_path / "sessions" / "old.json")
    new_time = time.time() + 10
    os.utime(old_path, (new_time, new_time))
    assert store.latest_id() == "old"



def test_save_rejects_empty_session_id(tmp_path):
    store = SessionStore(tmp_path / 'sessions')
    try:
        store.save('', {'session_id': ''})
        assert False, 'Expected ValueError'
    except ValueError:
        pass


def test_load_rejects_empty_session_id(tmp_path):
    store = SessionStore(tmp_path / 'sessions')
    try:
        store.load('')
        assert False, 'Expected ValueError'
    except ValueError:
        pass


def test_save_rejects_dotdot_session_id(tmp_path):
    store = SessionStore(tmp_path / 'sessions')
    try:
        store.save('..', {'session_id': '..'})
        assert False, 'Expected ValueError'
    except ValueError:
        pass


def test_save_rejects_slash_session_id(tmp_path):
    store = SessionStore(tmp_path / 'sessions')
    try:
        store.save('..\\outside', {'session_id': '..\\outside'})
        assert False, 'Expected ValueError'
    except ValueError:
        pass


def test_save_rejects_backslash_session_id(tmp_path):
    store = SessionStore(tmp_path / 'sessions')
    try:
        store.save('..\\outside', {'session_id': '..\\outside'})
        assert False, 'Expected ValueError'
    except ValueError:
        pass


def test_save_rejects_colon_session_id(tmp_path):
    store = SessionStore(tmp_path / 'sessions')
    try:
        store.save('a:b', {'session_id': 'a:b'})
        assert False, 'Expected ValueError'
    except ValueError:
        pass


def test_save_accepts_safe_ids(tmp_path):
    store = SessionStore(tmp_path / 'sessions')
    for sid in ['default', 'mysession', 'feature-1', 'user.name', 'a_b']:
        store.save(sid, {'session_id': sid})
        loaded = store.load(sid)
        assert loaded is not None
        assert loaded['session_id'] == sid


def test_latest_id_skips_unsafe_filenames(tmp_path):
    store = SessionStore(tmp_path / 'sessions')
    sessions_dir = tmp_path / 'sessions'
    sessions_dir.mkdir(parents=True)
    (sessions_dir / 'good.json').write_text('{"session_id": "good"}', encoding='utf-8')
    (sessions_dir / '...outside.json').write_text('{"session_id": "bad"}', encoding='utf-8')
    latest = store.latest_id()
    assert latest == 'good'
