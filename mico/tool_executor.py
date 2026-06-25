import json
from dataclasses import dataclass, field

from .tools import TOOL_SPECS, execute_validated_tool, is_shell_interpreter, validate_tool


@dataclass(frozen=True)
class ToolResult:
    content: str
    metadata: dict = field(default_factory=dict)


def _extract_tool_metadata(content):
    """If content is a JSON string containing __tool_metadata__, extract and return it."""
    if not isinstance(content, str):
        return None
    try:
        parsed = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(parsed, dict) or "__tool_metadata__" not in parsed:
        return None
    meta = dict(parsed["__tool_metadata__"])
    # Build a clean content string without __tool_metadata__
    clean = {k: v for k, v in parsed.items() if k != "__tool_metadata__"}
    meta["__content__"] = json.dumps(clean, ensure_ascii=False)
    return meta


class ToolExecutor:
    def __init__(self, workspace, approval_policy="auto", approval_callback=None):
        self.workspace = workspace
        self.approval_policy = approval_policy
        self.approval_callback = approval_callback
        self._last_tool_signature = None
        self._patched_old_texts = {}

    def reset_run_state(self):
        self._last_tool_signature = None
        self._patched_old_texts.clear()

    def tool_catalog(self):
        from .tools import build_tool_catalog

        return build_tool_catalog(self.approval_policy)

    def tool_summary(self):
        summary = []
        for item in self.tool_catalog():
            summary.append({
                "name": item["name"],
                "schema": item["schema"],
                "requires_approval": item["requires_approval"],
                "read_only": item["read_only"],
                "concurrency_safe": item["concurrency_safe"],
                "max_result_chars": item["max_result_chars"],
                "allowed": item["allowed"],
            })
        return summary

    def restricted_tools(self):
        return [item["name"] for item in self.tool_catalog() if not item["allowed"]]

    def _base_metadata(self, name, requires_approval):
        return {
            "tool_name": name,
            "approval_policy": self.approval_policy,
            "requires_approval": requires_approval,
            "blocked_by_approval": False,
            "repeated_call": False,
        }

    def execute(self, name, args):
        spec = TOOL_SPECS.get(name)
        args = args or {}
        requires_approval = bool(spec.requires_approval) if spec else False
        metadata = self._base_metadata(name, requires_approval)

        if spec is None:
            return ToolResult(
                content=f"error: unknown tool: {name}",
                metadata={**metadata, "ok": False, "error_kind": "unknown_tool"},
            )

        try:
            validate_tool(self.workspace, name, args)
        except ValueError as exc:
            return ToolResult(
                content=f"error: {exc}",
                metadata={**metadata, "ok": False, "error_kind": "validation_error"},
            )

        signature = name + "\0" + json.dumps(args, sort_keys=True, ensure_ascii=False)
        if signature == self._last_tool_signature:
            return ToolResult(
                content=f"error: repeated identical tool call for {name}",
                metadata={**metadata, "ok": False, "repeated_call": True, "error_kind": "repeated_call"},
            )

        patch_old_text_key = None
        if name == "patch_file":
            path = self.workspace.relative(self.workspace.path(args["path"]))
            patch_old_text_key = (path, args["old_text"])
            previous_new_text = self._patched_old_texts.get(patch_old_text_key)
            if previous_new_text is not None and previous_new_text != args["new_text"]:
                return ToolResult(
                    content=f"error: repeated stale patch_file old_text for {path}",
                    metadata={**metadata, "ok": False, "repeated_call": True, "error_kind": "repeated_call"},
                )

        if spec.requires_approval and self.approval_policy == "never":
            self._last_tool_signature = signature
            return ToolResult(
                content=f"error: tool {name} is not allowed under approval=never",
                metadata={**metadata, "ok": False, "blocked_by_approval": True, "error_kind": "approval_denied"},
            )

        if spec.requires_approval and self.approval_policy == "ask" and name == "run_command":
            argv = args.get("argv", [])
            if is_shell_interpreter(argv):
                if self.approval_callback is None or not self.approval_callback(argv):
                    self._last_tool_signature = signature
                    return ToolResult(
                        content=f"error: shell command not approved: {argv[0]}",
                        metadata={**metadata, "ok": False, "blocked_by_approval": True, "error_kind": "approval_denied"},
                    )

        try:
            content = execute_validated_tool(self.workspace, name, args)
        except ValueError as exc:
            return ToolResult(
                content=f"error: {exc}",
                metadata={**metadata, "ok": False, "error_kind": "validation_error"},
            )
        self._last_tool_signature = signature
        extracted_metadata = _extract_tool_metadata(content)
        if extracted_metadata is not None:
            clean_content = extracted_metadata.pop("__content__", content)
            result_metadata = {**metadata, **extracted_metadata}
            if (
                patch_old_text_key is not None
                and result_metadata.get("ok") is True
                and result_metadata.get("error_kind") == "ok"
            ):
                self._patched_old_texts[patch_old_text_key] = args["new_text"]
            return ToolResult(
                content=clean_content,
                metadata=result_metadata,
            )
        if patch_old_text_key is not None:
            self._patched_old_texts[patch_old_text_key] = args["new_text"]
        return ToolResult(
            content=content,
            metadata={**metadata, "ok": True, "error_kind": "ok"},
        )
