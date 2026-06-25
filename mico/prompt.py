import shutil
import sys
from dataclasses import dataclass, field


_SHELL_NAMES = [
    "cmd", "cmd.exe", "powershell", "powershell.exe",
    "pwsh", "pwsh.exe", "bash", "bash.exe", "sh", "sh.exe",
]


def detect_available_shells():
    """Return list of shell interpreter names found on PATH via shutil.which()."""
    return [name for name in _SHELL_NAMES if shutil.which(name)]


@dataclass(frozen=True)
class PromptBundle:
    text: str
    metadata: dict = field(default_factory=dict)


class PromptBuilder:
    MAX_HISTORY_ITEMS = 6

    def build(self, *, tool_catalog, approval_policy, workspace_root,
              user_message, history):
        history_items_total = len(history)
        recent = history[-self.MAX_HISTORY_ITEMS:]
        history_items_used = len(recent)

        text = (
            f"{self._static_prefix()}\n"
            f"{self._response_contract()}\n\n"
            f"{self._runtime_policy(approval_policy)}\n"
            f"{self._tool_catalog(tool_catalog)}\n\n"
            f"{self._system_context()}\n"
            f"{self._workspace_context(workspace_root)}\n"
            f"{self._current_request(user_message)}\n"
            f"{self._recent_history(recent)}\n"
            f"{self._format_reminder()}\n"
        )

        tool_count = len(tool_catalog)
        restricted_tool_count = sum(1 for t in tool_catalog if not t["allowed"])

        metadata = {
            "prompt_chars": len(text),
            "history_items_total": history_items_total,
            "history_items_used": history_items_used,
            "tool_count": tool_count,
            "restricted_tool_count": restricted_tool_count,
            "approval_policy": approval_policy,
            "current_request_chars": len(user_message),
        }
        return PromptBundle(text=text, metadata=metadata)

    @staticmethod
    def _static_prefix():
        return "You are mico, a local coding agent that can read, write, and run code in a sandboxed workspace."

    @staticmethod
    def _response_contract():
        return (
            "Respond with exactly one XML block per turn:\n"
            '<tool>{"name":"tool_name","args":{}}</tool>\n'
            "<final>answer</final>\n"
            "No text outside the XML block. Do not explain or narrate between tool calls.\n"
            "After creating or editing a file, do not repeat or refine the same operation. "
            "Do not read or list files solely to inspect your own edit. "
            "When the requested change is complete, respond with <final> immediately."
        )

    @staticmethod
    def _runtime_policy(approval_policy):
        return (
            f"Approval policy: {approval_policy}\n"
            "Do not call tools that are not allowed under the current approval policy."
        )

    @staticmethod
    def _tool_catalog(tool_catalog):
        lines = []
        for item in tool_catalog:
            availability = "allowed" if item["allowed"] else "not allowed under approval=never"
            approval_tag = "requires-approval" if item["requires_approval"] else "read-only"
            lines.append(
                f"- {item['name']}: {item['description']} "
                f"schema={item['schema']} [{approval_tag}; {availability}]"
            )
        return f"Available tools:\n" + "\n".join(lines)

    @staticmethod
    def _workspace_context(workspace_root):
        return f"Workspace: {workspace_root}"

    @staticmethod
    def _system_context():
        platform = sys.platform
        available = detect_available_shells()
        shells_str = ", ".join(available) if available else "(none detected)"
        if platform == "win32":
            guidance = "On Windows, prefer cmd.exe or powershell/pwsh. Avoid bash/sh unless listed as available."
        elif platform == "darwin":
            guidance = "On macOS, use bash or sh. cmd/powershell are not available."
        else:
            guidance = "On Linux, use bash or sh. cmd/powershell are not available."
        return f"OS: {platform}\nAvailable shells: {shells_str}\nGuidance: {guidance}"

    @staticmethod
    def _current_request(user_message):
        return f"User request: {user_message}"

    @staticmethod
    def _recent_history(recent):
        if not recent:
            return "Recent history:\n(empty)"
        lines = []
        for item in recent:
            role = item.get("role", "unknown")
            content = item.get("content", "")
            if role == "tool":
                lines.append(f"Tool result from {item.get('name')}: {content}")
            else:
                lines.append(f"{role}: {content}")
        return "Recent history:\n" + "\n".join(lines)

    @staticmethod
    def _format_reminder():
        return (
            "Reminder: respond with exactly one <tool> or <final> block. No prose outside the block.\n"
            "After creating or editing a file, state what you did in one sentence. Do not restate the contents or walk through changes."
        )
