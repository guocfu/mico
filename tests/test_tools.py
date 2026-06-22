import os

import pytest

from mico.tools import run_tool
from mico.workspace import Workspace


def test_list_files(tmp_path):
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")
    (tmp_path / "a").mkdir()
    workspace = Workspace.build(tmp_path)

    result = run_tool(workspace, "list_files", {"path": "."})

    assert "[D] a" in result
    assert "[F] b.txt" in result


def test_read_file_with_line_range(tmp_path):
    (tmp_path / "notes.txt").write_text("one\ntwo\nthree\n", encoding="utf-8")
    workspace = Workspace.build(tmp_path)

    result = run_tool(workspace, "read_file", {"path": "notes.txt", "start": 2, "end": 3})

    assert "# notes.txt" in result
    assert "2: two" in result
    assert "3: three" in result


def test_search(tmp_path):
    (tmp_path / "notes.txt").write_text("hello mico\nbye\n", encoding="utf-8")
    workspace = Workspace.build(tmp_path)

    result = run_tool(workspace, "search", {"pattern": "mico", "path": "."})

    assert "mico" in result


def test_workspace_blocks_path_escape(tmp_path):
    workspace = Workspace.build(tmp_path)

    with pytest.raises(ValueError, match="escapes workspace"):
        workspace.path("../outside.txt")


def test_workspace_blocks_symlink_escape(tmp_path):
    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    outside.write_text("secret", encoding="utf-8")
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink not supported on this platform")
    workspace = Workspace.build(tmp_path)

    with pytest.raises(ValueError, match="escapes workspace"):
        workspace.path("link.txt")


def test_workspace_allows_normal_path(tmp_path):
    (tmp_path / "file.txt").write_text("hello", encoding="utf-8")
    workspace = Workspace.build(tmp_path)

    result = workspace.path("file.txt")

    assert result == (tmp_path / "file.txt").resolve()


def test_workspace_blocks_cross_drive_path(tmp_path, monkeypatch):
    workspace = Workspace.build(tmp_path)

    def fake_commonpath(paths):
        raise ValueError("paths are on different drives")

    monkeypatch.setattr(os.path, "commonpath", fake_commonpath)

    with pytest.raises(ValueError, match="escapes workspace"):
        workspace.path("file.txt")


class TestPatchFile:
    def test_success(self, tmp_path):
        (tmp_path / "code.py").write_text("hello world\n", encoding="utf-8")
        workspace = Workspace.build(tmp_path)

        result = run_tool(workspace, "patch_file", {
            "path": "code.py",
            "old_text": "hello",
            "new_text": "goodbye",
        })

        assert "patched" in result
        assert (tmp_path / "code.py").read_text(encoding="utf-8") == "goodbye world\n"

    def test_no_match(self, tmp_path):
        (tmp_path / "code.py").write_text("hello world\n", encoding="utf-8")
        workspace = Workspace.build(tmp_path)

        with pytest.raises(ValueError, match="not found"):
            run_tool(workspace, "patch_file", {
                "path": "code.py",
                "old_text": "notfound",
                "new_text": "x",
            })

        assert (tmp_path / "code.py").read_text(encoding="utf-8") == "hello world\n"

    def test_multiple_matches(self, tmp_path):
        (tmp_path / "code.py").write_text("aaa\naaa\n", encoding="utf-8")
        workspace = Workspace.build(tmp_path)

        with pytest.raises(ValueError, match="2 times"):
            run_tool(workspace, "patch_file", {
                "path": "code.py",
                "old_text": "aaa",
                "new_text": "b",
            })

        assert (tmp_path / "code.py").read_text(encoding="utf-8") == "aaa\naaa\n"

    def test_missing_new_text(self, tmp_path):
        (tmp_path / "code.py").write_text("hello\n", encoding="utf-8")
        workspace = Workspace.build(tmp_path)

        with pytest.raises(ValueError, match="new_text field is required"):
            run_tool(workspace, "patch_file", {
                "path": "code.py",
                "old_text": "hello",
            })

    def test_empty_old_text(self, tmp_path):
        (tmp_path / "code.py").write_text("hello\n", encoding="utf-8")
        workspace = Workspace.build(tmp_path)

        with pytest.raises(ValueError, match="old_text must not be empty"):
            run_tool(workspace, "patch_file", {
                "path": "code.py",
                "old_text": "",
                "new_text": "x",
            })

    def test_path_escape(self, tmp_path):
        workspace = Workspace.build(tmp_path)

        with pytest.raises(ValueError, match="escapes workspace"):
            run_tool(workspace, "patch_file", {
                "path": "../outside.txt",
                "old_text": "a",
                "new_text": "b",
            })

    def test_path_not_file(self, tmp_path):
        (tmp_path / "dir").mkdir()
        workspace = Workspace.build(tmp_path)

        with pytest.raises(ValueError, match="not a file"):
            run_tool(workspace, "patch_file", {
                "path": "dir",
                "old_text": "a",
                "new_text": "b",
            })
