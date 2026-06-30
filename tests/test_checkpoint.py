"""Tests for mico.checkpoint module."""

import hashlib
from pathlib import Path

import pytest

from mico.checkpoint import (
    CHECKPOINT_FULL_VALID_STATUS,
    CHECKPOINT_NONE_STATUS,
    CHECKPOINT_PARTIAL_STALE_STATUS,
    CHECKPOINT_SCHEMA_MISMATCH_STATUS,
    CHECKPOINT_WORKSPACE_MISMATCH_STATUS,
    CHECKPOINT_SCHEMA_VERSION,
    RUNTIME_IDENTITY_KEYS,
    create_checkpoint,
    current_checkpoint,
    current_runtime_identity,
    ensure_checkpoint_shape,
    evaluate_resume_state,
    file_freshness,
    render_checkpoint_text,
    tool_signature,
    workspace_fingerprint,
)
from mico.memory import SessionMemoryState


# --- helpers ---

class FakeAgent:
    """Minimal agent stub for checkpoint tests."""

    def __init__(self, workspace_root, tmp_path):
        self.workspace = type("W", (), {"root": tmp_path})()
        self.session_id = "test-session"
        self.approval_policy = "auto"
        self.max_steps = 8
        self.session_memory = SessionMemoryState()
        self.session = {
            "checkpoints": {},
            "resume_state": {},
            "runtime_identity": {},
        }
        self.tool_executor = FakeToolExecutor()


class FakeToolExecutor:
    def tool_catalog(self):
        return [
            {"name": "list_files", "schema": "{}", "requires_approval": False, "read_only": True, "allowed": True},
            {"name": "patch_file", "schema": '{"path":"str","old":"str","new":"str"}', "requires_approval": True, "read_only": False, "allowed": True},
        ]


def _make_file(tmp_path, rel, content="hello"):
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


# --- file_freshness ---

class TestFileFreshness:
    def test_missing_path_returns_missing(self, tmp_path):
        assert file_freshness(str(tmp_path / "nope.txt"), str(tmp_path)) == "missing"

    def test_directory_returns_dir(self, tmp_path):
        d = tmp_path / "subdir"
        d.mkdir()
        assert file_freshness(str(d), str(tmp_path)) == "dir"

    def test_file_returns_sha256_prefix(self, tmp_path):
        p = _make_file(tmp_path, "a.txt", "content")
        result = file_freshness(str(p), str(tmp_path))
        assert result.startswith("sha256:")
        expected = hashlib.sha256(b"content").hexdigest()[:16]
        assert result == "sha256:" + expected


# --- workspace_fingerprint ---

class TestWorkspaceFingerprint:
    def test_empty_workspace(self, tmp_path):
        fp = workspace_fingerprint(str(tmp_path))
        assert isinstance(fp, str)
        assert len(fp) == 16

    def test_ignores_git_and_mico(self, tmp_path):
        _make_file(tmp_path, ".git/config", "git")
        _make_file(tmp_path, ".mico/state.json", "{}")
        fp = workspace_fingerprint(str(tmp_path))
        # Should be the same as empty since .git and .mico are ignored
        empty = tmp_path / "empty_ws"
        empty.mkdir()
        assert fp == workspace_fingerprint(str(empty))

    def test_changes_when_file_changes(self, tmp_path):
        _make_file(tmp_path, "a.txt", "v1")
        fp1 = workspace_fingerprint(str(tmp_path))
        _make_file(tmp_path, "a.txt", "v2")
        fp2 = workspace_fingerprint(str(tmp_path))
        assert fp1 != fp2


# --- tool_signature ---

class TestToolSignature:
    def test_deterministic(self):
        catalog = [
            {"name": "a", "schema": "{}", "requires_approval": False, "read_only": True, "allowed": True},
        ]
        assert tool_signature(catalog) == tool_signature(catalog)

    def test_changes_when_catalog_changes(self):
        c1 = [{"name": "a", "schema": "{}", "requires_approval": False, "read_only": True, "allowed": True}]
        c2 = [{"name": "b", "schema": "{}", "requires_approval": False, "read_only": True, "allowed": True}]
        assert tool_signature(c1) != tool_signature(c2)


# --- ensure_checkpoint_shape / current_checkpoint ---

class TestCheckpointShape:
    def test_ensure_shape_on_empty_session(self):
        session = {}
        shape = ensure_checkpoint_shape(session)
        assert shape["current_id"] is None
        assert shape["history"] == []
        assert "items" in shape

    def test_ensure_shape_preserves_existing(self):
        session = {"checkpoints": {"current_id": "abc", "history": ["abc"]}}
        shape = ensure_checkpoint_shape(session)
        assert shape["current_id"] == "abc"

    def test_current_checkpoint_none(self):
        session = {"checkpoints": {"current_id": None, "history": []}}
        assert current_checkpoint(session) is None

    def test_current_checkpoint_found(self, tmp_path):
        cp = {"checkpoint_id": "x", "trigger": "final"}
        session = {"checkpoints": {"current_id": "x", "history": ["x"], "items": {"x": cp}}}
        assert current_checkpoint(session) == cp


# --- evaluate_resume_state ---

class TestEvaluateResumeState:
    def test_no_checkpoint(self, tmp_path):
        agent = FakeAgent(str(tmp_path), tmp_path)
        result = evaluate_resume_state(agent)
        assert result["status"] == CHECKPOINT_NONE_STATUS
        assert result["checkpoint"] is None

    def test_schema_mismatch(self, tmp_path):
        agent = FakeAgent(str(tmp_path), tmp_path)
        agent.session["checkpoints"] = {
            "current_id": "c1",
            "history": ["c1"],
            "items": {"c1": {"checkpoint_id": "c1", "schema_version": "old"}},
        }
        result = evaluate_resume_state(agent)
        assert result["status"] == CHECKPOINT_SCHEMA_MISMATCH_STATUS

    def test_full_valid(self, tmp_path):
        agent = FakeAgent(str(tmp_path), tmp_path)
        _make_file(tmp_path, "src/main.py", "code")
        agent.session_memory.recent_files = ["src/main.py"]
        freshness = file_freshness(str(tmp_path / "src/main.py"), str(tmp_path))
        agent.session_memory.record_file_summary("src/main.py", "code", freshness=freshness)

        cp = {
            "checkpoint_id": "c1",
            "schema_version": CHECKPOINT_SCHEMA_VERSION,
            "key_files": {"src/main.py": freshness},
            "runtime_identity": current_runtime_identity(agent),
            "task_state": {"user_message": "do stuff", "summary": "did stuff"},
            "trigger": "final",
        }
        agent.session["checkpoints"] = {
            "current_id": "c1",
            "history": ["c1"],
            "items": {"c1": cp},
        }
        result = evaluate_resume_state(agent)
        assert result["status"] == CHECKPOINT_FULL_VALID_STATUS

    def test_partial_stale_key_file(self, tmp_path):
        agent = FakeAgent(str(tmp_path), tmp_path)
        _make_file(tmp_path, "src/main.py", "v1")
        old_freshness = file_freshness(str(tmp_path / "src/main.py"), str(tmp_path))
        agent.session_memory.record_file_summary("src/main.py", "old summary", freshness=old_freshness)
        agent.session_memory.recent_files = ["src/main.py"]

        # Change the file
        _make_file(tmp_path, "src/main.py", "v2")

        cp = {
            "checkpoint_id": "c1",
            "schema_version": CHECKPOINT_SCHEMA_VERSION,
            "key_files": {"src/main.py": old_freshness},
            "runtime_identity": current_runtime_identity(agent),
            "task_state": {"user_message": "do stuff", "summary": "did stuff"},
            "trigger": "final",
        }
        agent.session["checkpoints"] = {
            "current_id": "c1",
            "history": ["c1"],
            "items": {"c1": cp},
        }
        result = evaluate_resume_state(agent)
        assert result["status"] == CHECKPOINT_PARTIAL_STALE_STATUS
        assert "src/main.py" in result["stale_paths"]
        # Stale file summary should be invalidated
        assert "src/main.py" not in agent.session_memory.file_summaries

    def test_workspace_mismatch(self, tmp_path):
        agent = FakeAgent(str(tmp_path), tmp_path)
        cp = {
            "checkpoint_id": "c1",
            "schema_version": CHECKPOINT_SCHEMA_VERSION,
            "key_files": {},
            "runtime_identity": {
                "cwd": "/other/place",
                "model": "gpt-4",
                "model_client": "openai",
                "approval_policy": "never",
                "max_steps": 4,
                "workspace_fingerprint": "DIFFERENT",
                "tool_signature": "DIFFERENT",
            },
            "task_state": {"user_message": "do stuff", "summary": "did stuff"},
            "trigger": "final",
        }
        agent.session["checkpoints"] = {
            "current_id": "c1",
            "history": ["c1"],
            "items": {"c1": cp},
        }
        result = evaluate_resume_state(agent)
        assert result["status"] == CHECKPOINT_WORKSPACE_MISMATCH_STATUS
        assert len(result["runtime_identity_mismatch_fields"]) > 0

    def test_key_file_change_surfaces_as_partial_stale(self, tmp_path):
        agent = FakeAgent(str(tmp_path), tmp_path)
        _make_file(tmp_path, 'src/main.py', 'v1')
        old_freshness = file_freshness(str(tmp_path / 'src/main.py'), str(tmp_path))
        agent.session_memory.record_file_summary('src/main.py', 'old summary', freshness=old_freshness)
        agent.session_memory.recent_files = ['src/main.py']
        old_identity = current_runtime_identity(agent)
        _make_file(tmp_path, 'src/main.py', 'v2')
        cp = {
            'checkpoint_id': 'c1',
            'schema_version': CHECKPOINT_SCHEMA_VERSION,
            'key_files': {'src/main.py': old_freshness},
            'runtime_identity': old_identity,
            'task_state': {'user_message': 'do stuff', 'summary': 'did stuff'},
            'trigger': 'final',
        }
        agent.session['checkpoints'] = {
            'current_id': 'c1',
            'history': ['c1'],
            'items': {'c1': cp},
        }
        result = evaluate_resume_state(agent)
        assert result['status'] == CHECKPOINT_PARTIAL_STALE_STATUS
        assert 'src/main.py' in result['stale_paths']
        assert 'src/main.py' not in agent.session_memory.file_summaries


# --- render_checkpoint_text ---

class TestRenderCheckpointText:
    def test_no_checkpoint(self, tmp_path):
        agent = FakeAgent(str(tmp_path), tmp_path)
        text = render_checkpoint_text(agent)
        assert "no checkpoint" in text.lower() or text == ""

    def test_valid_checkpoint_includes_sections(self, tmp_path):
        agent = FakeAgent(str(tmp_path), tmp_path)
        cp = {
            "checkpoint_id": "c1",
            "schema_version": CHECKPOINT_SCHEMA_VERSION,
            "key_files": {},
            "runtime_identity": current_runtime_identity(agent),
            "task_state": {"user_message": "build login", "summary": "built login page", "next_step": "add tests"},
            "trigger": "final",
        }
        agent.session["checkpoints"] = {
            "current_id": "c1",
            "history": ["c1"],
            "items": {"c1": cp},
        }
        agent.resume_state = evaluate_resume_state(agent)
        text = render_checkpoint_text(agent)
        assert "Task checkpoint" in text
        assert "build login" in text
        assert "built login" in text

    def test_stale_paths_warned(self, tmp_path):
        agent = FakeAgent(str(tmp_path), tmp_path)
        _make_file(tmp_path, "a.py", "v1")
        old_fp = file_freshness(str(tmp_path / "a.py"), str(tmp_path))
        agent.session_memory.record_file_summary("a.py", "old", freshness=old_fp)
        agent.session_memory.recent_files = ["a.py"]
        _make_file(tmp_path, "a.py", "v2")

        cp = {
            "checkpoint_id": "c1",
            "schema_version": CHECKPOINT_SCHEMA_VERSION,
            "key_files": {"a.py": old_fp},
            "runtime_identity": current_runtime_identity(agent),
            "task_state": {"user_message": "task", "summary": "summary"},
            "trigger": "final",
        }
        agent.session["checkpoints"] = {
            "current_id": "c1",
            "history": ["c1"],
            "items": {"c1": cp},
        }
        agent.resume_state = evaluate_resume_state(agent)
        text = render_checkpoint_text(agent)
        assert "a.py" in text
        assert "stale" in text.lower() or "changed" in text.lower()


# --- create_checkpoint ---

class TestCreateCheckpoint:
    def test_creates_checkpoint_with_trigger(self, tmp_path):
        agent = FakeAgent(str(tmp_path), tmp_path)
        _make_file(tmp_path, "x.py", "code")
        agent.session_memory.recent_files = ["x.py"]
        agent.session_memory.set_task_summary("my task")

        cp = create_checkpoint(agent, {"summary": "did it", "next_step": "verify"}, "my task", "final")
        assert cp["schema_version"] == CHECKPOINT_SCHEMA_VERSION
        assert cp["trigger"] == "final"
        assert cp["task_state"]["summary"] == "did it"
        assert "x.py" in cp["key_files"]

    def test_checkpoint_stored_in_session(self, tmp_path):
        agent = FakeAgent(str(tmp_path), tmp_path)
        cp = create_checkpoint(agent, {"summary": "s"}, "t", "final")
        assert agent.session["checkpoints"]["current_id"] == cp["checkpoint_id"]
        assert cp["checkpoint_id"] in agent.session["checkpoints"]["items"]
    def test_second_checkpoint_replaces_first(self, tmp_path):
        agent = FakeAgent(str(tmp_path), tmp_path)
        cp1 = create_checkpoint(agent, {"summary": "first"}, "task1", "final")
        cp2 = create_checkpoint(agent, {"summary": "second"}, "task2", "final")
        items = agent.session["checkpoints"]["items"]
        assert len(items) == 1
        assert cp2["checkpoint_id"] in items
        assert cp1["checkpoint_id"] not in items
        assert agent.session["checkpoints"]["current_id"] == cp2["checkpoint_id"]

    def test_history_not_accumulated(self, tmp_path):
        agent = FakeAgent(str(tmp_path), tmp_path)
        create_checkpoint(agent, {"summary": "a"}, "t1", "final")
        create_checkpoint(agent, {"summary": "b"}, "t2", "final")
        history = agent.session["checkpoints"].get("history", [])
        assert len(history) <= 1

    def test_old_session_with_history_and_multiple_items_loads(self, tmp_path):
        session = {
            "checkpoints": {
                "current_id": "old2",
                "history": ["old1", "old2"],
                "items": {
                    "old1": {"checkpoint_id": "old1", "schema_version": CHECKPOINT_SCHEMA_VERSION, "trigger": "final", "task_state": {"user_message": "t1"}},
                    "old2": {"checkpoint_id": "old2", "schema_version": CHECKPOINT_SCHEMA_VERSION, "trigger": "final", "task_state": {"user_message": "t2"}},
                },
            },
            "resume_state": {},
            "runtime_identity": {},
        }
        ensure_checkpoint_shape(session)
        cp = current_checkpoint(session)
        assert cp is not None
        assert cp["checkpoint_id"] == "old2"

    def test_current_checkpoint_returns_latest_after_replacement(self, tmp_path):
        agent = FakeAgent(str(tmp_path), tmp_path)
        cp1 = create_checkpoint(agent, {"summary": "first"}, "t1", "final")
        cp2 = create_checkpoint(agent, {"summary": "second"}, "t2", "final")
        result = current_checkpoint(agent.session)
        assert result["checkpoint_id"] == cp2["checkpoint_id"]
        assert result["task_state"]["summary"] == "second"

