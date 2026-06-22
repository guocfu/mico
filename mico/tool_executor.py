from dataclasses import dataclass, field

from .tools import run_tool


@dataclass(frozen=True)
class ToolResult:
    content: str
    metadata: dict = field(default_factory=dict)


class ToolExecutor:
    def __init__(self, workspace, approval_policy="auto"):
        self.workspace = workspace
        self.approval_policy = approval_policy

    def execute(self, name, args):
        content = run_tool(self.workspace, name, args)
        return ToolResult(
            content=content,
            metadata={"approval_policy": self.approval_policy, "ok": True},
        )
