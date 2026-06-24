from .agent_loop import AgentLoop
from .parser import ModelOutputParser
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
        self._model_output_parser = ModelOutputParser()
        self._last_parser_error_kind = None

    def ask(self, user_message):
        self.tool_executor.reset_run_state()
        self._last_parser_error_kind = None
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
        parsed = ModelOutputParser().parse(raw)
        return parsed.kind, parsed.payload

    def parse_output(self, raw):
        parsed = self._model_output_parser.parse(raw)
        if parsed.kind == "retry":
            self._last_parser_error_kind = parsed.error_kind
        else:
            self._last_parser_error_kind = None
        return parsed

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
        changed_files = []
        changed_file_set = set()
        patches_applied = 0
        for item in self.history:
            if item.get("role") != "tool":
                continue
            error_kind = item.get("metadata", {}).get("error_kind", "unknown")
            tool_call_summary[error_kind] = tool_call_summary.get(error_kind, 0) + 1
            if error_kind != "ok":
                last_error_kind = error_kind
            if item.get("name") == "patch_file" and item.get("metadata", {}).get("ok") is True:
                patches_applied += 1
                path = item.get("args", {}).get("path")
                if path and path not in changed_file_set:
                    changed_file_set.add(path)
                    changed_files.append(path)
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
            "changed_files": changed_files,
            "patches_applied": patches_applied,
        }
        if self._last_prompt_metadata is not None:
            report["prompt_metadata"] = self._last_prompt_metadata
        if self._last_parser_error_kind is not None:
            report["parser_error_kind"] = self._last_parser_error_kind
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
