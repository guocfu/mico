import json
import os

import pytest

from mico.tools import TOOL_SPECS, run_tool
from mico.workspace import Workspace, clip_artifact


def _run_cmd(workspace, args):
    """Helper: run_command returns JSON with __tool_metadata__ + content fields."""
    raw = run_tool(workspace, "run_command", args)
    parsed = json.loads(raw)
    meta = parsed.pop("__tool_metadata__", {})
    return {**meta, **parsed}


def _run_cmd_via_executor(workspace, args, approval_policy="auto"):
    """Helper: run through ToolExecutor to get ToolResult with metadata."""
    from mico.tool_executor import ToolExecutor
    executor = ToolExecutor(workspace, approval_policy=approval_policy)
    return executor.execute("run_command", args)


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


def test_patch_file_requires_approval():
    assert TOOL_SPECS["patch_file"].requires_approval is True


def test_remember_tool_requires_approval_and_is_not_readonly():
    assert TOOL_SPECS["remember"].requires_approval is True
    assert TOOL_SPECS["remember"].read_only is False
    assert TOOL_SPECS["remember"].concurrency_safe is False


@pytest.mark.parametrize("name", ["list_files", "read_file", "search"])
def test_readonly_tools_do_not_require_approval(name):
    assert TOOL_SPECS[name].requires_approval is False


class TestRememberTool:
    def test_validate_accepts_valid_args(self, tmp_path):
        from mico.tools import validate_tool

        workspace = Workspace.build(tmp_path)

        validate_tool(workspace, "remember", {
            "topic": "preferences",
            "note": "Prefer pytest for verification.",
            "tags": ["testing"],
        })

    def test_validate_rejects_invalid_topic(self, tmp_path):
        from mico.tools import validate_tool

        workspace = Workspace.build(tmp_path)

        with pytest.raises(ValueError, match="Invalid topic"):
            validate_tool(workspace, "remember", {
                "topic": "../outside",
                "note": "bad",
            })

    def test_validate_rejects_empty_note(self, tmp_path):
        from mico.tools import validate_tool

        workspace = Workspace.build(tmp_path)

        with pytest.raises(ValueError, match="note"):
            validate_tool(workspace, "remember", {
                "topic": "notes",
                "note": " ",
            })

    def test_validate_rejects_non_string_note(self, tmp_path):
        from mico.tools import validate_tool

        workspace = Workspace.build(tmp_path)

        with pytest.raises(ValueError, match="note"):
            validate_tool(workspace, "remember", {
                "topic": "notes",
                "note": 123,
            })

    def test_executor_uses_custom_handler_under_auto(self, tmp_path):
        from mico.tool_executor import ToolExecutor

        workspace = Workspace.build(tmp_path)
        calls = []

        def _handler(args):
            calls.append(dict(args))
            return json.dumps({
                "__tool_metadata__": {
                    "ok": True,
                    "error_kind": "ok",
                    "topic": args["topic"],
                },
                "remembered": True,
            })

        executor = ToolExecutor(
            workspace,
            approval_policy="auto",
            custom_handlers={"remember": _handler},
        )

        result = executor.execute("remember", {
            "topic": "preferences",
            "note": "Prefer pytest.",
        })

        assert calls == [{"topic": "preferences", "note": "Prefer pytest."}]
        assert result.metadata["ok"] is True
        assert result.metadata["topic"] == "preferences"
        assert "remembered" in result.content

    def test_executor_denies_remember_under_never(self, tmp_path):
        from mico.tool_executor import ToolExecutor

        workspace = Workspace.build(tmp_path)
        calls = []
        executor = ToolExecutor(
            workspace,
            approval_policy="never",
            custom_handlers={"remember": lambda args: calls.append(args) or "ok"},
        )

        result = executor.execute("remember", {
            "topic": "preferences",
            "note": "Prefer pytest.",
        })

        assert calls == []
        assert result.metadata["ok"] is False
        assert result.metadata["error_kind"] == "approval_denied"

    def test_executor_asks_for_remember_approval(self, tmp_path):
        from mico.tool_executor import ToolExecutor

        workspace = Workspace.build(tmp_path)
        requests = []
        calls = []

        def _approval(request):
            requests.append(request)
            return True

        def _handler(args):
            calls.append(dict(args))
            return "remembered preferences"

        executor = ToolExecutor(
            workspace,
            approval_policy="ask",
            approval_callback=_approval,
            custom_handlers={"remember": _handler},
        )

        result = executor.execute("remember", {
            "topic": "preferences",
            "note": "Prefer pytest.",
            "tags": ["testing"],
        })

        assert requests[0]["tool_name"] == "remember"
        assert requests[0]["args"]["topic"] == "preferences"
        assert calls == [{"topic": "preferences", "note": "Prefer pytest.", "tags": ["testing"]}]
        assert result.metadata["ok"] is True

    def test_executor_denies_remember_when_ask_callback_denies(self, tmp_path):
        from mico.tool_executor import ToolExecutor

        workspace = Workspace.build(tmp_path)
        calls = []
        executor = ToolExecutor(
            workspace,
            approval_policy="ask",
            approval_callback=lambda request: False,
            custom_handlers={"remember": lambda args: calls.append(args) or "ok"},
        )

        result = executor.execute("remember", {
            "topic": "preferences",
            "note": "Prefer pytest.",
        })

        assert calls == []
        assert result.metadata["ok"] is False
        assert result.metadata["error_kind"] == "approval_denied"


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


def test_patch_file_already_applied_returns_metadata_ok(tmp_path):
    (tmp_path / "code.py").write_text("new\n", encoding="utf-8")
    workspace = Workspace.build(tmp_path)

    result = run_tool(workspace, "patch_file", {
        "path": "code.py",
        "old_text": "old",
        "new_text": "new",
    })

    parsed = json.loads(result)
    assert parsed["__tool_metadata__"]["ok"] is True
    assert parsed["__tool_metadata__"]["error_kind"] == "already_applied"
    assert parsed["__tool_metadata__"]["already_applied"] is True
    assert parsed["path"] == "code.py"
    assert (tmp_path / "code.py").read_text(encoding="utf-8") == "new\n"


class TestWriteFile:
    def test_creates_new_file(self, tmp_path):
        workspace = Workspace.build(tmp_path)
        result = run_tool(workspace, "write_file", {"path": "new.txt", "content": "hello"})
        assert "written" in result
        assert (tmp_path / "new.txt").read_text(encoding="utf-8") == "hello"

    def test_creates_parent_directories(self, tmp_path):
        workspace = Workspace.build(tmp_path)
        result = run_tool(workspace, "write_file", {"path": "sub/dir/file.txt", "content": "nested"})
        assert "written" in result
        assert (tmp_path / "sub" / "dir" / "file.txt").read_text(encoding="utf-8") == "nested"

    def test_overwrites_existing_file(self, tmp_path):
        (tmp_path / "exist.txt").write_text("old", encoding="utf-8")
        workspace = Workspace.build(tmp_path)
        result = run_tool(workspace, "write_file", {"path": "exist.txt", "content": "new"})
        assert "written" in result
        assert (tmp_path / "exist.txt").read_text(encoding="utf-8") == "new"

    def test_rejects_path_escape(self, tmp_path):
        workspace = Workspace.build(tmp_path)
        with pytest.raises(ValueError, match="escapes workspace"):
            run_tool(workspace, "write_file", {"path": "../outside.txt", "content": "x"})

    def test_rejects_directory_target(self, tmp_path):
        (tmp_path / "dir").mkdir()
        workspace = Workspace.build(tmp_path)
        with pytest.raises(ValueError, match="not a file"):
            run_tool(workspace, "write_file", {"path": "dir", "content": "x"})

    def test_rejects_git_directory(self, tmp_path):
        workspace = Workspace.build(tmp_path)
        with pytest.raises(ValueError, match="ignored"):
            run_tool(workspace, "write_file", {"path": ".git/config", "content": "x"})

    def test_rejects_mico_directory(self, tmp_path):
        workspace = Workspace.build(tmp_path)
        with pytest.raises(ValueError, match="ignored"):
            run_tool(workspace, "write_file", {"path": ".mico/data", "content": "x"})

    def test_rejects_venv_directory(self, tmp_path):
        workspace = Workspace.build(tmp_path)
        with pytest.raises(ValueError, match="ignored"):
            run_tool(workspace, "write_file", {"path": ".venv/lib/pkg.py", "content": "x"})

    def test_rejects_node_modules(self, tmp_path):
        workspace = Workspace.build(tmp_path)
        with pytest.raises(ValueError, match="ignored"):
            run_tool(workspace, "write_file", {"path": "node_modules/pkg/index.js", "content": "x"})

    def test_rejects_pycache(self, tmp_path):
        workspace = Workspace.build(tmp_path)
        with pytest.raises(ValueError, match="ignored"):
            run_tool(workspace, "write_file", {"path": "__pycache__/mod.cpython-312.pyc", "content": "x"})

    def test_rejects_pytest_cache(self, tmp_path):
        workspace = Workspace.build(tmp_path)
        with pytest.raises(ValueError, match="ignored"):
            run_tool(workspace, "write_file", {"path": ".pytest_cache/v/cache/lastfailed", "content": "x"})

    def test_requires_approval(self):
        assert TOOL_SPECS["write_file"].requires_approval is True

    def test_not_read_only(self):
        assert TOOL_SPECS["write_file"].read_only is False

    def test_not_concurrency_safe(self):
        assert TOOL_SPECS["write_file"].concurrency_safe is False

    def test_returns_byte_count(self, tmp_path):
        workspace = Workspace.build(tmp_path)
        result = run_tool(workspace, "write_file", {"path": "out.txt", "content": "abc"})
        assert "bytes=" in result
        assert "3" in result


class TestRunCommand:
    def test_successful_command(self, tmp_path):
        workspace = Workspace.build(tmp_path)
        result = _run_cmd(workspace, {"argv": ["python", "-c", "print('hello')"]})
        assert result["ok"] is True
        assert result["error_kind"] == "ok"
        assert "hello" in result["stdout"]
        assert result["exit_code"] == 0

    def test_nonzero_exit(self, tmp_path):
        workspace = Workspace.build(tmp_path)
        result = _run_cmd(workspace, {"argv": ["python", "-c", "import sys; sys.exit(1)"]})
        assert result["ok"] is False
        assert result["error_kind"] == "command_failed"
        assert result["exit_code"] == 1

    def test_stderr_captured(self, tmp_path):
        workspace = Workspace.build(tmp_path)
        result = _run_cmd(workspace, {"argv": ["python", "-c", "import sys; sys.stderr.write('err\\n')"]})
        assert result["ok"] is True
        assert "err" in result["stderr"]

    def test_timeout(self, tmp_path):
        workspace = Workspace.build(tmp_path)
        result = _run_cmd(workspace, {"argv": ["python", "-c", "import time; time.sleep(10)"], "timeout": 1})
        assert result["ok"] is False
        assert result["error_kind"] == "command_timed_out"

    def test_command_not_found(self, tmp_path):
        workspace = Workspace.build(tmp_path)
        result = _run_cmd(workspace, {"argv": ["nonexistent_command_xyz"]})
        assert result["ok"] is False
        assert result["error_kind"] == "command_error"

    def test_rejects_string_argv(self, tmp_path):
        workspace = Workspace.build(tmp_path)
        with pytest.raises(ValueError, match="list"):
            run_tool(workspace, "run_command", {"argv": "ls"})

    def test_rejects_empty_argv(self, tmp_path):
        workspace = Workspace.build(tmp_path)
        with pytest.raises(ValueError, match="non-empty"):
            run_tool(workspace, "run_command", {"argv": []})

    def test_rejects_non_string_argv(self, tmp_path):
        workspace = Workspace.build(tmp_path)
        with pytest.raises(ValueError, match="string"):
            run_tool(workspace, "run_command", {"argv": [1, 2]})

    @pytest.mark.parametrize("interpreter", [
        "cmd", "cmd.exe", "powershell", "powershell.exe",
        "pwsh", "pwsh.exe", "bash", "bash.exe", "sh", "sh.exe",
    ])
    def test_shell_interpreter_passes_validation(self, tmp_path, interpreter):
        """Shell interpreters are no longer hard-rejected by validate_tool."""
        from mico.tools import validate_tool
        workspace = Workspace.build(tmp_path)
        # validate_tool should not raise ValueError about "shell interpreter not allowed"
        validate_tool(workspace, "run_command", {"argv": [interpreter, "-c", "echo hello"]})

    def test_requires_approval(self):
        assert TOOL_SPECS["run_command"].requires_approval is True

    def test_not_read_only(self):
        assert TOOL_SPECS["run_command"].read_only is False

    def test_not_concurrency_safe(self):
        assert TOOL_SPECS["run_command"].concurrency_safe is False

    def test_stdout_truncated(self, tmp_path):
        workspace = Workspace.build(tmp_path)
        long_output = "x" * 2000
        result = _run_cmd(workspace, {"argv": ["python", "-c", f"print('{long_output}')"]})
        assert result["ok"] is True
        assert len(result["stdout"]) <= 1000

    def test_stderr_truncated(self, tmp_path):
        workspace = Workspace.build(tmp_path)
        long_err = "y" * 2000
        result = _run_cmd(workspace, {"argv": ["python", "-c", f"import sys; sys.stderr.write('{long_err}')"]})
        assert result["ok"] is True
        assert len(result["stderr"]) <= 1000

    def test_metadata_ok_on_success(self, tmp_path):
        workspace = Workspace.build(tmp_path)
        tr = _run_cmd_via_executor(workspace, {"argv": ["python", "-c", "print(1)"]})
        assert tr.metadata["ok"] is True
        assert tr.metadata["error_kind"] == "ok"
        assert tr.metadata["exit_code"] == 0
        assert tr.metadata["timed_out"] is False

    def test_metadata_ok_false_on_failure(self, tmp_path):
        workspace = Workspace.build(tmp_path)
        tr = _run_cmd_via_executor(workspace, {"argv": ["python", "-c", "import sys; sys.exit(2)"]})
        assert tr.metadata["ok"] is False
        assert tr.metadata["error_kind"] == "command_failed"
        assert tr.metadata["exit_code"] == 2
        assert tr.metadata["timed_out"] is False

    def test_metadata_on_timeout(self, tmp_path):
        workspace = Workspace.build(tmp_path)
        tr = _run_cmd_via_executor(workspace, {"argv": ["python", "-c", "import time; time.sleep(10)"], "timeout": 1})
        assert tr.metadata["ok"] is False
        assert tr.metadata["error_kind"] == "command_timed_out"
        assert tr.metadata["exit_code"] is None
        assert tr.metadata["timed_out"] is True

    def test_metadata_on_command_not_found(self, tmp_path):
        workspace = Workspace.build(tmp_path)
        tr = _run_cmd_via_executor(workspace, {"argv": ["nonexistent_command_xyz"]})
        assert tr.metadata["ok"] is False
        assert tr.metadata["error_kind"] == "command_error"
        assert tr.metadata["exit_code"] is None
        assert tr.metadata["timed_out"] is False

    def test_command_error_content_is_readable(self, tmp_path):
        workspace = Workspace.build(tmp_path)
        tr = _run_cmd_via_executor(workspace, {"argv": ["nonexistent_command_xyz"]})
        assert tr.content != "{}"
        assert len(tr.content) > 0
        assert "nonexistent_command_xyz" in tr.content or "No such file" in tr.content or "not found" in tr.content.lower() or "errno" in tr.content.lower() or "winerror" in tr.content.lower()
        assert "stderr_tail" in tr.metadata

    def test_metadata_has_duration_ms_on_success(self, tmp_path):
        workspace = Workspace.build(tmp_path)
        tr = _run_cmd_via_executor(workspace, {"argv": ["python", "-c", "print(1)"]})
        assert "duration_ms" in tr.metadata
        assert isinstance(tr.metadata["duration_ms"], int)
        assert tr.metadata["duration_ms"] >= 0

    def test_metadata_has_duration_ms_on_failure(self, tmp_path):
        workspace = Workspace.build(tmp_path)
        tr = _run_cmd_via_executor(workspace, {"argv": ["python", "-c", "import sys; sys.exit(1)"]})
        assert "duration_ms" in tr.metadata
        assert isinstance(tr.metadata["duration_ms"], int)
        assert tr.metadata["duration_ms"] >= 0

    def test_metadata_has_duration_ms_on_timeout(self, tmp_path):
        workspace = Workspace.build(tmp_path)
        tr = _run_cmd_via_executor(workspace, {"argv": ["python", "-c", "import time; time.sleep(10)"], "timeout": 1})
        assert "duration_ms" in tr.metadata
        assert isinstance(tr.metadata["duration_ms"], int)
        assert tr.metadata["duration_ms"] >= 0

    def test_metadata_has_duration_ms_on_command_not_found(self, tmp_path):
        workspace = Workspace.build(tmp_path)
        tr = _run_cmd_via_executor(workspace, {"argv": ["nonexistent_command_xyz"]})
        assert "duration_ms" in tr.metadata
        assert isinstance(tr.metadata["duration_ms"], int)
        assert tr.metadata["duration_ms"] >= 0

    def test_metadata_has_stdout_tail_stderr_tail_on_success(self, tmp_path):
        workspace = Workspace.build(tmp_path)
        tr = _run_cmd_via_executor(workspace, {"argv": ["python", "-c", "print('hello')"]})
        assert "stdout_tail" in tr.metadata
        assert "stderr_tail" in tr.metadata
        assert "hello" in tr.metadata["stdout_tail"]

    def test_metadata_has_stdout_tail_stderr_tail_on_failure(self, tmp_path):
        workspace = Workspace.build(tmp_path)
        tr = _run_cmd_via_executor(workspace, {"argv": ["python", "-c", "import sys; sys.stderr.write('err\\n'); sys.exit(1)"]})
        assert "stdout_tail" in tr.metadata
        assert "stderr_tail" in tr.metadata
        assert "err" in tr.metadata["stderr_tail"]

    def test_metadata_has_stdout_tail_stderr_tail_on_command_not_found(self, tmp_path):
        workspace = Workspace.build(tmp_path)
        tr = _run_cmd_via_executor(workspace, {"argv": ["nonexistent_command_xyz"]})
        assert "stdout_tail" in tr.metadata
        assert "stderr_tail" in tr.metadata

    def test_rejects_timeout_none(self, tmp_path):
        workspace = Workspace.build(tmp_path)
        with pytest.raises(ValueError):
            run_tool(workspace, "run_command", {"argv": ["python", "-c", "print(1)"], "timeout": None})

    def test_rejects_timeout_non_numeric_string(self, tmp_path):
        workspace = Workspace.build(tmp_path)
        with pytest.raises(ValueError):
            run_tool(workspace, "run_command", {"argv": ["python", "-c", "print(1)"], "timeout": "abc"})

    def test_rejects_timeout_float(self, tmp_path):
        workspace = Workspace.build(tmp_path)
        with pytest.raises(ValueError):
            run_tool(workspace, "run_command", {"argv": ["python", "-c", "print(1)"], "timeout": 1.9})

    def test_rejects_timeout_bool(self, tmp_path):
        workspace = Workspace.build(tmp_path)
        with pytest.raises(ValueError):
            run_tool(workspace, "run_command", {"argv": ["python", "-c", "print(1)"], "timeout": True})


class TestClipArtifact:
    def test_short_string_unchanged(self):
        assert clip_artifact("hello") == "hello"

    def test_long_string_clipped(self):
        result = clip_artifact("x" * 600)
        assert len(result) == 500
        assert result.endswith("...")

    def test_custom_limit(self):
        result = clip_artifact("x" * 100, limit=50)
        assert len(result) == 50
        assert result.endswith("...")

    def test_dict_values_clipped(self):
        result = clip_artifact({"key": "a" * 600})
        assert len(result["key"]) == 500
        assert result["key"].endswith("...")

    def test_dict_keys_preserved(self):
        result = clip_artifact({"short_key": "val"})
        assert "short_key" in result

    def test_list_items_clipped(self):
        result = clip_artifact(["a" * 600, "short"])
        assert len(result[0]) == 500
        assert result[1] == "short"

    def test_tuple_items_clipped(self):
        result = clip_artifact(("a" * 600, "b"))
        assert isinstance(result, tuple)
        assert len(result[0]) == 500
        assert result[1] == "b"

    def test_int_unchanged(self):
        assert clip_artifact(42) == 42

    def test_none_unchanged(self):
        assert clip_artifact(None) is None

    def test_nested_structure(self):
        result = clip_artifact({"args": {"old_text": "x" * 600, "new_text": "y" * 600}})
        assert len(result["args"]["old_text"]) == 500
        assert len(result["args"]["new_text"]) == 500
        assert result["args"]["old_text"].endswith("...")


class TestIsShellInterpreter:
    def test_cmd(self):
        from mico.tools import is_shell_interpreter
        assert is_shell_interpreter(["cmd", "/c", "dir"]) is True

    def test_cmd_exe(self):
        from mico.tools import is_shell_interpreter
        assert is_shell_interpreter(["cmd.exe", "/c", "dir"]) is True

    def test_powershell(self):
        from mico.tools import is_shell_interpreter
        assert is_shell_interpreter(["powershell", "-c", "dir"]) is True

    def test_pwsh(self):
        from mico.tools import is_shell_interpreter
        assert is_shell_interpreter(["pwsh", "-c", "dir"]) is True

    def test_bash(self):
        from mico.tools import is_shell_interpreter
        assert is_shell_interpreter(["bash", "-c", "ls"]) is True

    def test_sh(self):
        from mico.tools import is_shell_interpreter
        assert is_shell_interpreter(["sh", "-c", "ls"]) is True

    def test_python_not_shell(self):
        from mico.tools import is_shell_interpreter
        assert is_shell_interpreter(["python", "-c", "print(1)"]) is False

    def test_empty_argv(self):
        from mico.tools import is_shell_interpreter
        assert is_shell_interpreter([]) is False

    def test_full_path_bash(self):
        from mico.tools import is_shell_interpreter
        assert is_shell_interpreter(["/bin/bash", "-c", "ls"]) is True

    def test_case_insensitive(self):
        from mico.tools import is_shell_interpreter
        assert is_shell_interpreter(["CMD", "/c", "dir"]) is True
        assert is_shell_interpreter(["Bash", "-c", "ls"]) is True
