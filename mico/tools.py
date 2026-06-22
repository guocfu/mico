import shutil
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class ToolSpec:
    description: str
    schema: str
    risky: bool = False


TOOL_SPECS = {
    "list_files": ToolSpec("List files in the workspace.", '{"path": "str=."}'),
    "read_file": ToolSpec("Read a UTF-8 file by line range.", '{"path": "str", "start": "int=1", "end": "int=80"}'),
    "search": ToolSpec("Search text in the workspace.", '{"pattern": "str", "path": "str=."}'),
    "patch_file": ToolSpec("Exact text replacement in a file.", '{"path": "str", "old_text": "str", "new_text": "str"}', risky=True),
}


def validate_tool(workspace, name, args):
    if name not in TOOL_SPECS:
        raise ValueError(f"unknown tool: {name}")
    args = args or {}
    if name == "list_files":
        path = workspace.path(args.get("path", "."))
        if not path.is_dir():
            raise ValueError("path is not a directory")
        return
    if name == "read_file":
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
        path = workspace.path(args["path"])
        if not path.is_file():
            raise ValueError("path is not a file")
        old_text = str(args.get("old_text", ""))
        if not old_text:
            raise ValueError("old_text must not be empty")
        if "new_text" not in args:
            raise ValueError("new_text field is required")
        return


def run_tool(workspace, name, args):
    validate_tool(workspace, name, args)
    if name == "list_files":
        return _list_files(workspace, args)
    if name == "read_file":
        return _read_file(workspace, args)
    if name == "search":
        return _search(workspace, args)
    if name == "patch_file":
        return _patch_file(workspace, args)
    raise ValueError(f"unknown tool: {name}")


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
        raise ValueError("old_text not found in file")
    if count > 1:
        raise ValueError(f"old_text found {count} times, expected exactly 1")
    updated = content.replace(old_text, new_text, 1)
    path.write_text(updated, encoding="utf-8")
    return f"patched {workspace.relative(path)}"
