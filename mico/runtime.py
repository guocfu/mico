import json
import re

from .agent_loop import AgentLoop
from .security import redact_artifact
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
        self.tool_executor.reset_run_state()
        return AgentLoop(self).run(user_message)

    def record(self, item):
        self.history.append(dict(item))

    def execute_tool(self, name, args):
        return self.tool_executor.execute(name, args)

    def emit_trace(self, task_state, event_type, payload=None):
        event = {"event": event_type, "run_id": task_state.run_id, **dict(payload or {})}
        self.run_store.append_trace(task_state, redact_artifact(event))

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
        tool_lines = []
        for item in self.tool_executor.tool_catalog():
            availability = "allowed" if item["allowed"] else "not allowed under approval=never"
            approval_tag = "requires-approval" if item["requires_approval"] else "read-only"
            tool_lines.append(
                f"- {item['name']}: {item['description']} schema={item['schema']} [{approval_tag}; {availability}]"
            )
        tool_catalog = "\n".join(tool_lines)
        return (
            "You are mico, a tiny local coding agent.\n"
            "Respond with exactly one XML block per turn:\n"
            '<tool>{"name":"tool_name","args":{}}</tool>\n'
            "<final>answer</final>\n\n"
            f"Approval policy: {self.approval_policy}\n"
            "Do not call tools that are not allowed under the current approval policy.\n"
            f"Available tools:\n{tool_catalog}\n\n"
            f"Workspace: {self.workspace.root}\n"
            f"User request: {user_message}\n"
            f"Recent history:\n{history}\n"
        )

    def build_report(self, task_state):
        tool_call_summary = {}
        last_error_kind = None
        for item in self.history:
            if item.get("role") != "tool":
                continue
            error_kind = item.get("metadata", {}).get("error_kind", "unknown")
            tool_call_summary[error_kind] = tool_call_summary.get(error_kind, 0) + 1
            if error_kind != "ok":
                last_error_kind = error_kind
        available_tools = [item["name"] for item in self.tool_executor.tool_catalog() if item["allowed"]]
        return redact_artifact({
            "artifacts_version": "1",
            "task_state": task_state.to_dict(),
            "failure_category": self._failure_category(task_state, last_error_kind),
            "history_items": len(self.history),
            "workspace_root": str(self.workspace.root),
            "approval_policy": self.approval_policy,
            "available_tools": available_tools,
            "restricted_tools": self.tool_executor.restricted_tools(),
            "tool_call_summary": tool_call_summary,
        })

    @staticmethod
    def _failure_category(task_state, last_error_kind):
        stop = task_state.stop_reason
        if stop == "final":
            return "success"
        if stop == "step_limit":
            return "step_limit"
        if stop == "retry_limit":
            return "malformed_model_output"
        if stop == "model_error":
            return "model_error"
        if last_error_kind:
            return last_error_kind
        return "unknown"
