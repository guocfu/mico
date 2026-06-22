import json
import re

from .agent_loop import AgentLoop
from .tool_executor import ToolExecutor


class Mico:
    def __init__(self, model_client, workspace, run_store, approval_policy="auto", max_steps=4):
        self.model_client = model_client
        self.workspace = workspace
        self.run_store = run_store
        self.approval_policy = approval_policy
        self.max_steps = max_steps
        self.history = []
        self.tool_executor = ToolExecutor(workspace, approval_policy=approval_policy)

    def ask(self, user_message):
        return AgentLoop(self).run(user_message)

    def record(self, item):
        self.history.append(dict(item))

    def execute_tool(self, name, args):
        return self.tool_executor.execute(name, args or {})

    def emit_trace(self, task_state, event_type, payload=None):
        event = {"event": event_type, "run_id": task_state.run_id, **dict(payload or {})}
        self.run_store.append_trace(task_state, event)

    @staticmethod
    def parse(raw):
        text = str(raw or "")
        tool_match = re.search(r"<tool>(.*?)</tool>", text, re.DOTALL)
        if tool_match:
            try:
                return "tool", json.loads(tool_match.group(1).strip())
            except json.JSONDecodeError as exc:
                return "retry", f"model returned malformed tool JSON: {exc}"
        final_match = re.search(r"<final>(.*?)</final>", text, re.DOTALL)
        if final_match:
            final = final_match.group(1).strip()
            if final:
                return "final", final
            return "retry", "model returned an empty final answer"
        return "retry", "model returned neither <tool> nor <final>"

    def build_prompt(self, user_message):
        history_lines = []
        for item in self.history[-6:]:
            role = item.get("role", "unknown")
            content = item.get("content", "")
            if role == "tool":
                history_lines.append(f"Tool result from {item.get('name')}: {content}")
            else:
                history_lines.append(f"{role}: {content}")
        history = "\n".join(history_lines) or "(empty)"
        return (
            "You are mico, a tiny local coding agent.\n"
            "Respond with exactly one of these XML blocks:\n"
            '<tool>{"name":"list_files","args":{"path":"."}}</tool>\n'
            '<tool>{"name":"read_file","args":{"path":"file","start":1,"end":80}}</tool>\n'
            '<tool>{"name":"search","args":{"pattern":"text","path":"."}}</tool>\n'
            '<tool>{"name":"patch_file","args":{"path":"file","old_text":"old","new_text":"new"}}</tool>\n'
            "<final>answer</final>\n\n"
            f"Workspace: {self.workspace.root}\n"
            f"User request: {user_message}\n"
            f"Recent history:\n{history}\n"
        )

    def build_report(self, task_state):
        return {
            "task_state": task_state.to_dict(),
            "history_items": len(self.history),
            "workspace_root": str(self.workspace.root),
        }
