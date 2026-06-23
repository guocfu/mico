import json
from dataclasses import dataclass, field

from .tools import TOOL_SPECS, execute_validated_tool, validate_tool


@dataclass(frozen=True)
class ToolResult:
    content: str
    metadata: dict = field(default_factory=dict)


class ToolExecutor:
    def __init__(self, workspace, approval_policy="auto"):
        self.workspace = workspace
        self.approval_policy = approval_policy
        self._last_tool_signature = None

    def reset_run_state(self):
        self._last_tool_signature = None

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

        if spec.requires_approval and self.approval_policy == "never":
            return ToolResult(
                content=f"error: tool {name} is not allowed under approval=never",
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
        return ToolResult(
            content=content,
            metadata={**metadata, "ok": True, "error_kind": "ok"},
        )
