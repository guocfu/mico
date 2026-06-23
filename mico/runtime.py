import json
import re

from .agent_loop import AgentLoop
from .prompt import PromptBuilder
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
        self._prompt_builder = PromptBuilder()
        self._last_prompt_metadata = None

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
        return self.build_prompt_bundle(user_message).text

    def build_prompt_bundle(self, user_message):
        bundle = self._prompt_builder.build(
            tool_catalog=self.tool_executor.tool_catalog(),
            approval_policy=self.approval_policy,
            workspace_root=str(self.workspace.root),
            user_message=user_message,
            history=self.history,
        )
        self._last_prompt_metadata = bundle.metadata
        return bundle

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
        report = {
            "artifacts_version": "1",
            "task_state": task_state.to_dict(),
            "failure_category": self._failure_category(task_state, last_error_kind),
            "history_items": len(self.history),
            "workspace_root": str(self.workspace.root),
            "approval_policy": self.approval_policy,
            "available_tools": available_tools,
            "restricted_tools": self.tool_executor.restricted_tools(),
            "tool_call_summary": tool_call_summary,
        }
        if self._last_prompt_metadata is not None:
            report["prompt_metadata"] = self._last_prompt_metadata
        return redact_artifact(report)

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
