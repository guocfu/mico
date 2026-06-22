from dataclasses import dataclass, field

from .tools import run_tool

WRITE_TOOLS = {"patch_file"}


@dataclass(frozen=True)
class ToolResult:
    content: str
    metadata: dict = field(default_factory=dict)


class ToolExecutor:
    def __init__(self, workspace, approval_policy="auto"):
        self.workspace = workspace
        self.approval_policy = approval_policy

    def execute(self, name, args):
        if name in WRITE_TOOLS and self.approval_policy == "never":
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
