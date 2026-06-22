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
