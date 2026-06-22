from dataclasses import dataclass, field

from .tools import TOOL_SPECS, run_tool


@dataclass(frozen=True)
class ToolResult:
    content: str
    metadata: dict = field(default_factory=dict)


class ToolExecutor:
    def __init__(self, workspace, approval_policy="auto"):
        self.workspace = workspace
        self.approval_policy = approval_policy

    def execute(self, name, args):
        spec = TOOL_SPECS.get(name)
        if spec and spec.risky and self.approval_policy == "never":
            return ToolResult(
                content=f"error: tool {name} is not allowed under approval=never",
                metadata={"approval_policy": self.approval_policy, "ok": False},
            )
        try:
            content = run_tool(self.workspace, name, args)
        except ValueError as exc:
            return ToolResult(
                content=f"error: {exc}",
                metadata={"approval_policy": self.approval_policy, "ok": False},
            )
        return ToolResult(
            content=content,
            metadata={"approval_policy": self.approval_policy, "ok": True},
        )
