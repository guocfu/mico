import json
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .memory_store import TOPICS as MEMORY_TOPICS


@dataclass(frozen=True)
class ToolSpec:
    description: str
    schema: str
    requires_approval: bool = False
    read_only: bool = True
    concurrency_safe: bool = True
    max_result_chars: int = 4000


SHELL_INTERPRETERS = frozenset({
    "cmd", "cmd.exe", "powershell", "powershell.exe",
    "pwsh", "pwsh.exe", "bash", "bash.exe", "sh", "sh.exe",
})


def is_shell_interpreter(argv):
    if not argv:
        return False
    prog = Path(argv[0]).name.lower()
    return prog in SHELL_INTERPRETERS


TOOL_SPECS = {
    "list_files": ToolSpec("List files in the workspace.", '{"path": "str=."}'),
    "read_file": ToolSpec("Read a UTF-8 file by line range.", '{"path": "str", "start": "int=1", "end": "int=80"}'),
    "search": ToolSpec("Search text in the workspace.", '{"pattern": "str", "path": "str=."}'),
    "patch_file": ToolSpec(
        "Exact text replacement in a file.",
        '{"path": "str", "old_text": "str", "new_text": "str"}',
        requires_approval=True,
        read_only=False,
        concurrency_safe=False,
    ),
    "write_file": ToolSpec(
        "Write UTF-8 content to a file, creating parent dirs if needed.",
        '{"path": "str", "content": "str"}',
        requires_approval=True,
        read_only=False,
        concurrency_safe=False,
    ),
    "run_command": ToolSpec(
        "Run a command as argv list with timeout.",
        '{"argv": "list[str]", "timeout": "int=30"}',
        requires_approval=True,
        read_only=False,
        concurrency_safe=False,
    ),
    "remember": ToolSpec(
        "Save a durable note to cross-session memory.",
        '{"topic": "str", "note": "str", "tags": "list[str]=[]"}',
        requires_approval=True,
        read_only=False,
        concurrency_safe=False,
    ),
}


def build_tool_catalog(approval_policy="auto"):
    catalog = []
    for name, spec in TOOL_SPECS.items():
        allowed = not (spec.requires_approval and approval_policy == "never")
        approval_note = "blocked under approval=never" if spec.requires_approval else "always allowed"
        catalog.append({
            "name": name,
            "description": spec.description,
            "schema": spec.schema,
            "requires_approval": spec.requires_approval,
            "read_only": spec.read_only,
            "concurrency_safe": spec.concurrency_safe,
            "max_result_chars": spec.max_result_chars,
            "allowed": allowed,
            "approval_note": approval_note,
        })
    return catalog


def validate_tool(workspace, name, args):
    if name not in TOOL_SPECS:
        raise ValueError(f"unknown tool: {name}")
    if not isinstance(args, dict):
        raise ValueError("tool args must be a JSON object")
    args = args or {}
    if name == "list_files":
        path = workspace.path(args.get("path", "."))
        if not path.is_dir():
            raise ValueError("path is not a directory")
        return
    if name == "read_file":
        if "path" not in args:
            raise ValueError("path field is required")
        path = workspace.path(args["path"])
        if not path.is_file():
            raise ValueError("path is not a file")
        start = int(args.get("start", 1))
        end = int(args.get("end", 80))
        if start < 1 or end < start:
            raise ValueError("invalid line range")
        return
    if name == "search":
        pattern = str(args.get("pattern", "")).strip()
        if not pattern:
            raise ValueError("pattern must not be empty")
        workspace.path(args.get("path", "."))
        return
    if name == "patch_file":
        if "path" not in args:
            raise ValueError("path field is required")
        path = workspace.path(args["path"])
        if not path.is_file():
            raise ValueError("path is not a file")
        old_text = str(args.get("old_text", ""))
        if not old_text:
            raise ValueError("old_text must not be empty")
        if "new_text" not in args:
            raise ValueError("new_text field is required")
        return
    if name == "write_file":
        if "path" not in args:
            raise ValueError("path field is required")
        if "content" not in args:
            raise ValueError("content field is required")
        path = workspace.path(args["path"])
        if path.is_dir():
            raise ValueError("path is a directory, not a file")
        parts = Path(args["path"]).parts
        if any(part in workspace.ignored_names for part in parts):
            raise ValueError("path targets an ignored directory")
        return
    if name == "run_command":
        argv = args.get("argv")
        if not isinstance(argv, list):
            raise ValueError("argv must be a list")
        if len(argv) == 0:
            raise ValueError("argv must be non-empty")
        for i, elem in enumerate(argv):
            if not isinstance(elem, str):
                raise ValueError(f"argv[{i}] must be a string, got {type(elem).__name__}")
        raw_timeout = args.get("timeout", 30)
        if isinstance(raw_timeout, bool) or not isinstance(raw_timeout, int):
            raise ValueError(f"timeout must be an integer, got {type(raw_timeout).__name__}")
        timeout = raw_timeout
        if timeout < 1:
            raise ValueError("timeout must be a positive integer")
        if timeout > 120:
            raise ValueError("timeout must be at most 120 seconds")
        return
    if name == "remember":
        topic = str(args.get("topic", "")).strip()
        if topic not in MEMORY_TOPICS:
            raise ValueError(f"Invalid topic {topic!r}. Must be one of: {', '.join(MEMORY_TOPICS)}")
        note = args.get("note", "")
        if not isinstance(note, str) or not note.strip():
            raise ValueError("note must not be empty")
        tags = args.get("tags", [])
        if not isinstance(tags, list):
            raise ValueError("tags must be a list")
        for i, tag in enumerate(tags):
            if not isinstance(tag, str):
                raise ValueError(f"tags[{i}] must be a string, got {type(tag).__name__}")
        return


def execute_validated_tool(workspace, name, args):
    if name == "list_files":
        return _list_files(workspace, args)
    if name == "read_file":
        return _read_file(workspace, args)
    if name == "search":
        return _search(workspace, args)
    if name == "patch_file":
        return _patch_file(workspace, args)
    if name == "write_file":
        return _write_file(workspace, args)
    if name == "run_command":
        return _run_command(workspace, args)
    if name == "remember":
        raise ValueError("remember requires a DurableMemory handler")
    raise ValueError(f"unknown tool: {name}")


def run_tool(workspace, name, args):
    validate_tool(workspace, name, args)
    return execute_validated_tool(workspace, name, args)


def _list_files(workspace, args):
    path = workspace.path(args.get("path", "."))
    entries = sorted(path.iterdir(), key=lambda item: (item.is_file(), item.name.lower()))
    lines = []
    for entry in entries[:120]:
        if entry.name in workspace.ignored_names:
            continue
        kind = "[D]" if entry.is_dir() else "[F]"
        lines.append(f"{kind} {workspace.relative(entry)}")
    return "\n".join(lines) or "(empty)"


def _read_file(workspace, args):
    path = workspace.path(args["path"])
    start = int(args.get("start", 1))
    end = int(args.get("end", 80))
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    body = "\n".join(
        f"{number:>4}: {line}" for number, line in enumerate(lines[start - 1 : end], start=start)
    )
    return f"# {workspace.relative(path)}\n{body}"


def _search(workspace, args):
    pattern = str(args["pattern"])
    path = workspace.path(args.get("path", "."))
    if shutil.which("rg"):
        result = subprocess.run(
            ["rg", "-n", "--smart-case", "--max-count", "80", pattern, str(path)],
            cwd=workspace.root,
            capture_output=True,
            text=True,
            check=False,
        )
        return result.stdout.strip() or "(no matches)"

    matches = []
    files = [path] if path.is_file() else [item for item in path.rglob("*") if item.is_file()]
    for file_path in files:
        if any(part in workspace.ignored_names for part in file_path.relative_to(workspace.root).parts):
            continue
        for number, line in enumerate(
            file_path.read_text(encoding="utf-8", errors="replace").splitlines(),
            start=1,
        ):
            if pattern.lower() in line.lower():
                matches.append(f"{workspace.relative(file_path)}:{number}:{line}")
                if len(matches) >= 80:
                    return "\n".join(matches)
    return "\n".join(matches) or "(no matches)"


def _patch_file(workspace, args):
    path = workspace.path(args["path"])
    old_text = str(args["old_text"])
    new_text = str(args["new_text"])
    content = path.read_text(encoding="utf-8")
    count = content.count(old_text)
    if count == 0:
        new_count = content.count(new_text)
        if new_count == 1:
            metadata = {
                "ok": True,
                "error_kind": "already_applied",
                "already_applied": True,
            }
            return json.dumps({
                "__tool_metadata__": metadata,
                "path": workspace.relative(path),
                "already_applied": True,
            }, ensure_ascii=False)
        if new_count > 1:
            raise ValueError("old_text not found and new_text found multiple times")
        raise ValueError("old_text not found in file")
    if count > 1:
        raise ValueError(f"old_text found {count} times, expected exactly 1")
    updated = content.replace(old_text, new_text, 1)
    path.write_text(updated, encoding="utf-8")
    return f"patched {workspace.relative(path)}"


def _write_file(workspace, args):
    path = workspace.path(args["path"])
    content = str(args["content"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    byte_count = len(content.encode("utf-8"))
    return f"written {workspace.relative(path)} bytes={byte_count}"


_MAX_STDOUT = 1000
_MAX_STDERR = 1000


def _run_command(workspace, args):
    argv = list(args["argv"])
    timeout = int(args.get("timeout", 30))
    started = time.monotonic()
    try:
        result = subprocess.run(
            argv,
            cwd=str(workspace.root),
            timeout=timeout,
            capture_output=True,
            text=True,
            shell=False,
        )
        duration_ms = int((time.monotonic() - started) * 1000)
        stdout = result.stdout[-_MAX_STDOUT:] if len(result.stdout) > _MAX_STDOUT else result.stdout
        stderr = result.stderr[-_MAX_STDERR:] if len(result.stderr) > _MAX_STDERR else result.stderr
        if result.returncode == 0:
            metadata = {
                "ok": True, "error_kind": "ok", "exit_code": 0,
                "timed_out": False, "duration_ms": duration_ms,
                "stdout_tail": stdout, "stderr_tail": stderr,
            }
            return json.dumps({
                "__tool_metadata__": metadata,
                "stdout": stdout,
                "stderr": stderr,
            })
        metadata = {
            "ok": False, "error_kind": "command_failed", "exit_code": result.returncode,
            "timed_out": False, "duration_ms": duration_ms,
            "stdout_tail": stdout, "stderr_tail": stderr,
        }
        return json.dumps({
            "__tool_metadata__": metadata,
            "stdout": stdout,
            "stderr": stderr,
        })
    except subprocess.TimeoutExpired as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        stdout = ""
        stderr = ""
        if exc.stdout:
            stdout = exc.stdout[-_MAX_STDOUT:] if len(exc.stdout) > _MAX_STDOUT else exc.stdout
        if exc.stderr:
            stderr = exc.stderr[-_MAX_STDERR:] if len(exc.stderr) > _MAX_STDERR else exc.stderr
        metadata = {
            "ok": False, "error_kind": "command_timed_out", "exit_code": None,
            "timed_out": True, "duration_ms": duration_ms,
            "stdout_tail": stdout, "stderr_tail": stderr,
        }
        return json.dumps({
            "__tool_metadata__": metadata,
            "stdout": stdout,
            "stderr": stderr,
        })
    except (FileNotFoundError, OSError) as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        metadata = {
            "ok": False, "error_kind": "command_error", "exit_code": None,
            "timed_out": False, "duration_ms": duration_ms,
            "stdout_tail": "", "stderr_tail": str(exc),
        }
        return json.dumps({
            "__tool_metadata__": metadata,
            "error": str(exc),
        })
