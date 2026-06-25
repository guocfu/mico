from .agent_loop import AgentLoop
from .parser import ModelOutputParser
from .prompt import PromptBuilder
from .security import redact_artifact
from .tool_executor import ToolExecutor


class Mico:
    def __init__(self, model_client, workspace, run_store, approval_policy="auto", max_steps=4, approval_callback=None, event_callback=None):
        self.model_client = model_client
        self.workspace = workspace
        self.run_store = run_store
        self.approval_policy = approval_policy
        self.max_steps = max_steps
        self.history = []
        self.tool_executor = ToolExecutor(workspace, approval_policy=approval_policy, approval_callback=approval_callback)
        self._prompt_builder = PromptBuilder()
        self._last_prompt_metadata = None
        self._model_output_parser = ModelOutputParser()
        self._last_parser_error_kind = None
        self._last_task_state = None
        self._last_run_history_start = 0
        self.event_callback = event_callback

    def emit_ui_event(self, event_type, payload=None):
        if self.event_callback is None:
            return
        try:
            self.event_callback(event_type, redact_artifact(payload))
        except Exception:
            pass

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

    def build_report(self, task_state, verification_result=None, history_start=None):
        if history_start is None:
            history_start = self._last_run_history_start
        report_history = self.history[history_start:]
        tool_call_summary = {}
        last_error_kind = None
        changed_files = []
        changed_file_set = set()
        patches_applied = 0
        files_written = []
        files_written_set = set()
        commands_run = []
        for item in report_history:
            if item.get("role") != "tool":
                continue
            error_kind = item.get("metadata", {}).get("error_kind", "unknown")
            tool_call_summary[error_kind] = tool_call_summary.get(error_kind, 0) + 1
            if error_kind != "ok":
                last_error_kind = error_kind
            if (
                item.get("name") == "patch_file"
                and item.get("metadata", {}).get("ok") is True
                and item.get("metadata", {}).get("error_kind") == "ok"
            ):
                patches_applied += 1
                path = item.get("args", {}).get("path")
                if path and path not in changed_file_set:
                    changed_file_set.add(path)
                    changed_files.append(path)
            if item.get("name") == "write_file" and item.get("metadata", {}).get("ok") is True:
                path = item.get("args", {}).get("path")
                if path and path not in changed_file_set:
                    changed_file_set.add(path)
                    changed_files.append(path)
                if path and path not in files_written_set:
                    files_written_set.add(path)
                    files_written.append(path)
            if item.get("name") == "run_command" and item.get("metadata", {}).get("error_kind") not in {"approval_denied", "validation_error", "unknown_tool", "repeated_call"}:
                meta = item.get("metadata", {})
                commands_run.append({
                    "argv": item.get("args", {}).get("argv"),
                    "exit_code": meta.get("exit_code"),
                    "timed_out": meta.get("timed_out", False),
                    "duration_ms": meta.get("duration_ms"),
                    "stdout_tail": meta.get("stdout_tail", ""),
                    "stderr_tail": meta.get("stderr_tail", ""),
                    "ok": meta.get("ok", False),
                    "error_kind": meta.get("error_kind", "unknown"),
                })
        available_tools = [item["name"] for item in self.tool_executor.tool_catalog() if item["allowed"]]
        report = {
            "artifacts_version": "1",
            "task_state": task_state.to_dict(),
            "failure_category": self._failure_category(task_state, last_error_kind),
            "history_items": len(report_history),
            "workspace_root": str(self.workspace.root),
            "approval_policy": self.approval_policy,
            "available_tools": available_tools,
            "restricted_tools": self.tool_executor.restricted_tools(),
            "tool_call_summary": tool_call_summary,
            "changed_files": changed_files,
            "files_written": files_written,
            "commands_run": commands_run,
            "patches_applied": patches_applied,
        }
        if self._last_prompt_metadata is not None:
            report["prompt_metadata"] = self._last_prompt_metadata
        if self._last_parser_error_kind is not None:
            report["parser_error_kind"] = self._last_parser_error_kind
        if verification_result is not None:
            report["verification_ok"] = verification_result.ok
            report["verification_exit_code"] = verification_result.exit_code
            report["verification_timed_out"] = verification_result.timed_out
            report["verification_summary"] = {
                "ok": verification_result.ok,
                "exit_code": verification_result.exit_code,
                "timed_out": verification_result.timed_out,
                "duration_ms": verification_result.duration_ms,
                "argv": verification_result.argv,
                "stdout_tail": verification_result.stdout_tail,
                "stderr_tail": verification_result.stderr_tail,
            }
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
