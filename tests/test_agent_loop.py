import json

import pytest

from mico.providers import FakeModelClient
from mico.session_store import SessionStore
from mico.runtime import Mico
from mico.state import RunStore
from mico.tool_executor import ToolExecutor
from mico.workspace import Workspace


class FailingModelClient:
    def __init__(self, error_message="connection refused"):
        self.error_message = error_message
        self.prompts = []

    def complete(self, prompt, *_args, **_kwargs):
        self.prompts.append(prompt)
        raise RuntimeError(self.error_message)


def _trace_events(run_root):
    run_dirs = list(run_root.iterdir())
    assert len(run_dirs) == 1
    trace_path = run_dirs[0] / "trace.jsonl"
    return [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]


def test_readonly_tool_allowed_under_approval_never(tmp_path):
    (tmp_path / "notes.txt").write_text("hello mico\nbye\n", encoding="utf-8")
    workspace = Workspace.build(tmp_path)
    executor = ToolExecutor(workspace, approval_policy="never")

    result = executor.execute("search", {"pattern": "mico", "path": "."})

    assert result.metadata["ok"] is True
    assert result.metadata["error_kind"] == "ok"
    assert result.metadata["blocked_by_approval"] is False
    assert "mico" in result.content


def test_agent_loop_runs_tool_and_returns_final(tmp_path):
    (tmp_path / "README.md").write_text("hello mico\n", encoding="utf-8")
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient(),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
    )

    answer = agent.ask("inspect files")

    assert "mico inspected" in answer
    assert agent.history[1]["role"] == "tool"
    run_dirs = list((tmp_path / ".mico" / "runs").iterdir())
    assert len(run_dirs) == 1
    assert (run_dirs[0] / "trace.jsonl").exists()
    assert (run_dirs[0] / "state.json").exists()
    assert (run_dirs[0] / "report.json").exists()


def test_agent_loop_retries_malformed_model_output(tmp_path):
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient(["not xml", "<final>done</final>"]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
    )

    assert agent.ask("hello") == "done"
    assert agent.history[1]["content"] == "model returned neither <tool> nor <final>"


def test_plain_text_after_successful_patch_file_finishes(tmp_path):
    (tmp_path / "code.py").write_text("old\n", encoding="utf-8")
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient([
            '<tool>{"name":"patch_file","args":{"path":"code.py","old_text":"old","new_text":"new"}}</tool>',
            "文件已更新。",
        ]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
    )

    answer = agent.ask("fix code")

    assert answer == "文件已更新。"
    assert (tmp_path / "code.py").read_text(encoding="utf-8") == "new\n"
    assert agent.history[-1]["role"] == "assistant"
    assert agent.history[-1]["content"] == "文件已更新。"
    assert all(item.get("content") != "model returned neither <tool> nor <final>" for item in agent.history)
    run_dirs = list((tmp_path / ".mico" / "runs").iterdir())
    state = json.loads((run_dirs[0] / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "success"
    assert state["stop_reason"] == "final"


def test_agent_loop_executes_patch_file(tmp_path):
    (tmp_path / "code.py").write_text("old content\n", encoding="utf-8")
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient([
            '<tool>{"name":"patch_file","args":{"path":"code.py","old_text":"old content","new_text":"new content"}}</tool>',
            "<final>patched</final>",
        ]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
    )

    answer = agent.ask("fix code")

    assert answer == "patched"
    assert (tmp_path / "code.py").read_text(encoding="utf-8") == "new content\n"
    assert agent.history[1]["role"] == "tool"
    assert agent.history[1]["name"] == "patch_file"


def test_agent_loop_patch_file_rejected_by_approval_never(tmp_path):
    (tmp_path / "code.py").write_text("old content\n", encoding="utf-8")
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient([
            '<tool>{"name":"patch_file","args":{"path":"code.py","old_text":"old content","new_text":"new content"}}</tool>',
            "<final>done</final>",
        ]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
        approval_policy="never",
    )

    answer = agent.ask("fix code")

    assert answer == "done"
    assert "not allowed" in agent.history[1]["content"]
    assert agent.history[1]["metadata"]["error_kind"] == "approval_denied"
    assert agent.history[1]["metadata"]["blocked_by_approval"] is True
    assert (tmp_path / "code.py").read_text(encoding="utf-8") == "old content\n"


def test_agent_loop_patch_file_allowed_by_approval_auto(tmp_path):
    (tmp_path / "code.py").write_text("old content\n", encoding="utf-8")
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient([
            '<tool>{"name":"patch_file","args":{"path":"code.py","old_text":"old content","new_text":"new content"}}</tool>',
            "<final>done</final>",
        ]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
        approval_policy="auto",
    )

    answer = agent.ask("fix code")

    assert answer == "done"
    assert (tmp_path / "code.py").read_text(encoding="utf-8") == "new content\n"


def test_agent_loop_patch_file_no_match_records_error(tmp_path):
    (tmp_path / "code.py").write_text("hello\n", encoding="utf-8")
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient([
            '<tool>{"name":"patch_file","args":{"path":"code.py","old_text":"notfound","new_text":"x"}}</tool>',
            "<final>done</final>",
        ]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
    )

    answer = agent.ask("fix code")

    assert answer == "done"
    assert "error" in agent.history[1]["content"]
    assert "not found" in agent.history[1]["content"]
    assert (tmp_path / "code.py").read_text(encoding="utf-8") == "hello\n"


def test_tool_executor_patch_file_failure_ok_false(tmp_path):
    (tmp_path / "code.py").write_text("hello\n", encoding="utf-8")
    workspace = Workspace.build(tmp_path)
    executor = ToolExecutor(workspace, approval_policy="auto")

    result = executor.execute("patch_file", {
        "path": "code.py",
        "old_text": "notfound",
        "new_text": "x",
    })

    assert "error" in result.content
    assert result.metadata["ok"] is False
    assert result.metadata["error_kind"] == "validation_error"


def test_tool_executor_approval_never_ok_false(tmp_path):
    (tmp_path / "code.py").write_text("hello\n", encoding="utf-8")
    workspace = Workspace.build(tmp_path)
    executor = ToolExecutor(workspace, approval_policy="never")

    result = executor.execute("patch_file", {
        "path": "code.py",
        "old_text": "hello",
        "new_text": "x",
    })

    assert "not allowed" in result.content
    assert result.metadata["ok"] is False
    assert result.metadata["error_kind"] == "approval_denied"
    assert result.metadata["blocked_by_approval"] is True
    assert (tmp_path / "code.py").read_text(encoding="utf-8") == "hello\n"


def test_repeated_consecutive_read_file_rejected(tmp_path):
    (tmp_path / "notes.txt").write_text("hello\n", encoding="utf-8")
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient([
            '<tool>{"name":"read_file","args":{"path":"notes.txt","start":1,"end":80}}</tool>',
            '<tool>{"name":"read_file","args":{"path":"notes.txt","start":1,"end":80}}</tool>',
            "<final>done</final>",
        ]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
    )

    answer = agent.ask("read file twice")

    assert answer == "done"
    assert agent.history[1]["role"] == "tool"
    assert "hello" in agent.history[1]["content"]
    assert "repeated" in agent.history[2]["content"]
    assert agent.history[2]["metadata"]["error_kind"] == "repeated_call"
    assert agent.history[2]["metadata"]["repeated_call"] is True


def test_repeated_consecutive_patch_file_no_second_edit(tmp_path):
    (tmp_path / "code.py").write_text("old\n", encoding="utf-8")
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient([
            '<tool>{"name":"patch_file","args":{"path":"code.py","old_text":"old","new_text":"new"}}</tool>',
            '<tool>{"name":"patch_file","args":{"path":"code.py","old_text":"old","new_text":"new"}}</tool>',
            "<final>done</final>",
        ]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
    )

    answer = agent.ask("patch twice")

    assert answer == "done"
    assert (tmp_path / "code.py").read_text(encoding="utf-8") == "new\n"
    assert "patched" in agent.history[1]["content"]
    assert "repeated" in agent.history[2]["content"]


def test_patch_file_same_change_absolute_then_relative_is_already_applied(tmp_path):
    (tmp_path / "code.py").write_text("old\n", encoding="utf-8")
    absolute_path = str(tmp_path / "code.py")
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient([
            f'<tool>{{"name":"patch_file","args":{{"path":{json.dumps(absolute_path)},"old_text":"old","new_text":"new"}}}}</tool>',
            '<tool>{"name":"patch_file","args":{"path":"code.py","old_text":"old","new_text":"new"}}</tool>',
            "<final>done</final>",
        ]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
    )

    answer = agent.ask("patch twice")

    assert answer == "done"
    assert (tmp_path / "code.py").read_text(encoding="utf-8") == "new\n"
    assert agent.history[1]["metadata"]["error_kind"] == "ok"
    assert agent.history[2]["metadata"]["ok"] is True
    assert agent.history[2]["metadata"]["error_kind"] == "already_applied"
    assert agent.history[2]["metadata"]["already_applied"] is True


def test_same_name_different_args_allowed(tmp_path):
    (tmp_path / "a.txt").write_text("aaa\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("bbb\n", encoding="utf-8")
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient([
            '<tool>{"name":"read_file","args":{"path":"a.txt","start":1,"end":80}}</tool>',
            '<tool>{"name":"read_file","args":{"path":"b.txt","start":1,"end":80}}</tool>',
            "<final>done</final>",
        ]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
    )

    answer = agent.ask("read two files")

    assert answer == "done"
    assert "aaa" in agent.history[1]["content"]
    assert "bbb" in agent.history[2]["content"]


def test_non_consecutive_repeat_allowed(tmp_path):
    (tmp_path / "notes.txt").write_text("hello\n", encoding="utf-8")
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient([
            '<tool>{"name":"read_file","args":{"path":"notes.txt","start":1,"end":80}}</tool>',
            '<tool>{"name":"list_files","args":{"path":"."}}</tool>',
            '<tool>{"name":"read_file","args":{"path":"notes.txt","start":1,"end":80}}</tool>',
            "<final>done</final>",
        ]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
    )

    answer = agent.ask("read, list, read again")

    assert answer == "done"
    assert "hello" in agent.history[1]["content"]
    assert "[F]" in agent.history[2]["content"]
    assert "hello" in agent.history[3]["content"]


def test_repeated_detection_resets_between_asks(tmp_path):
    (tmp_path / "notes.txt").write_text("hello\n", encoding="utf-8")
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient([
            '<tool>{"name":"read_file","args":{"path":"notes.txt","start":1,"end":80}}</tool>',
            "<final>first</final>",
            '<tool>{"name":"read_file","args":{"path":"notes.txt","start":1,"end":80}}</tool>',
            "<final>second</final>",
        ]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
    )

    first = agent.ask("first task")
    second = agent.ask("second task")

    assert first == "first"
    assert second == "second"
    # First ask: tool result at history[1]
    assert "hello" in agent.history[1]["content"]
    assert "repeated" not in agent.history[1]["content"]
    # Second ask: tool result at history[4] (after user msg + first ask's 2 items)
    assert "hello" in agent.history[4]["content"]
    assert "repeated" not in agent.history[4]["content"]


def test_repeated_tool_result_metadata_has_approval_policy(tmp_path):
    (tmp_path / "notes.txt").write_text("hello\n", encoding="utf-8")
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient(),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
        approval_policy="auto",
    )

    args = {"path": "notes.txt", "start": 1, "end": 80}
    first = agent.execute_tool("read_file", args)
    second = agent.execute_tool("read_file", args)

    assert first.metadata["ok"] is True
    assert "repeated" in second.content
    assert second.metadata["ok"] is False
    assert second.metadata["approval_policy"] == "auto"
    assert second.metadata["error_kind"] == "repeated_call"


def test_trace_clips_long_tool_args(tmp_path):
    long_old = "x" * 600
    long_new = "y" * 600
    (tmp_path / "code.py").write_text(long_old + "\n", encoding="utf-8")
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient([
            f'<tool>{{"name":"patch_file","args":{{"path":"code.py","old_text":"{long_old}","new_text":"{long_new}"}}}}</tool>',
            "<final>done</final>",
        ]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
    )

    answer = agent.ask("fix code")

    assert answer == "done"
    tool_events = [event for event in _trace_events(tmp_path / ".mico" / "runs") if event["event"] == "tool_executed"]
    assert len(tool_events) == 1
    event = tool_events[0]
    assert isinstance(event["args"], dict)
    assert len(event["args"]["old_text"]) == 500
    assert event["args"]["old_text"].endswith("...")
    assert len(event["args"]["new_text"]) == 500
    assert event["args"]["new_text"].endswith("...")
    assert event["error_kind"] == "ok"
    assert event["tool_name"] == "patch_file"


def test_history_preserves_full_tool_args(tmp_path):
    long_old = "a" * 600
    long_new = "b" * 600
    (tmp_path / "code.py").write_text(long_old + "\n", encoding="utf-8")
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient([
            f'<tool>{{"name":"patch_file","args":{{"path":"code.py","old_text":"{long_old}","new_text":"{long_new}"}}}}</tool>',
            "<final>done</final>",
        ]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
    )

    agent.ask("fix code")

    tool_entry = agent.history[1]
    assert tool_entry["role"] == "tool"
    assert tool_entry["args"]["old_text"] == long_old
    assert tool_entry["args"]["new_text"] == long_new


def test_trace_redaction_still_works_after_clipping(tmp_path, monkeypatch):
    monkeypatch.setenv("MY_SECRET", "secret-value-xyz")
    long_secret = "secret-value-xyz" * 40
    (tmp_path / "notes.txt").write_text("hello\n", encoding="utf-8")
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient([
            f'<tool>{{"name":"search","args":{{"pattern":"{long_secret}","path":"."}}}}</tool>',
            "<final>done</final>",
        ]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
    )

    agent.ask("search")

    events = _trace_events(tmp_path / ".mico" / "runs")
    full_text = json.dumps(events, ensure_ascii=False)
    assert "secret-value-xyz" not in full_text
    assert "[REDACTED]" in full_text


def test_tool_executor_unknown_tool_returns_stable_metadata(tmp_path):
    workspace = Workspace.build(tmp_path)
    executor = ToolExecutor(workspace, approval_policy="auto")

    result = executor.execute("missing_tool", {})

    assert result.metadata["ok"] is False
    assert result.metadata["tool_name"] == "missing_tool"
    assert result.metadata["error_kind"] == "unknown_tool"
    assert result.metadata["requires_approval"] is False


def test_tool_executor_missing_required_arg_is_validation_error(tmp_path):
    workspace = Workspace.build(tmp_path)
    executor = ToolExecutor(workspace, approval_policy="auto")

    result = executor.execute("read_file", {"start": 1, "end": 2})

    assert result.metadata["ok"] is False
    assert result.metadata["error_kind"] == "validation_error"
    assert "path field is required" in result.content


def test_prompt_includes_tool_catalog_and_approval_note(tmp_path):
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient(),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
        approval_policy="never",
    )

    prompt = agent.build_prompt("inspect files")

    assert "Available tools:" in prompt
    assert "patch_file" in prompt
    assert "not allowed under approval=never" in prompt
    assert "schema=" in prompt


def test_run_started_trace_includes_approval_and_tool_summary(tmp_path):
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient(["<final>ok</final>"]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
        approval_policy="never",
    )

    agent.ask("hello")

    events = _trace_events(tmp_path / ".mico" / "runs")
    started = [event for event in events if event["event"] == "run_started"]
    assert len(started) == 1
    event = started[0]
    assert event["approval_policy"] == "never"
    assert isinstance(event["tool_summary"], list)
    assert any(item["name"] == "patch_file" and item["allowed"] is False for item in event["tool_summary"])


def test_report_includes_restricted_tools_and_tool_call_summary(tmp_path):
    (tmp_path / "code.py").write_text("hello\n", encoding="utf-8")
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient([
            '<tool>{"name":"patch_file","args":{"path":"code.py","old_text":"hello","new_text":"x"}}</tool>',
            "<final>done</final>",
        ]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
        approval_policy="never",
    )

    agent.ask("fix code")

    run_dirs = list((tmp_path / ".mico" / "runs").iterdir())
    report = json.loads((run_dirs[0] / "report.json").read_text(encoding="utf-8"))
    assert report["approval_policy"] == "never"
    assert "patch_file" in report["restricted_tools"]
    assert report["tool_call_summary"]["approval_denied"] == 1
    assert report["artifacts_version"] == "1"
    # Task succeeded overall (model returned <final>), tool denial is in tool_call_summary
    assert report["failure_category"] == "success"
    assert report["changed_files"] == []
    assert report["patches_applied"] == 0


def test_report_counts_only_current_repl_run_history(tmp_path):
    (tmp_path / "first.txt").write_text("old\n", encoding="utf-8")
    (tmp_path / "second.txt").write_text("old\n", encoding="utf-8")
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient([
            '<tool>{"name":"patch_file","args":{"path":"first.txt","old_text":"old","new_text":"new"}}</tool>',
            "<final>first</final>",
            '<tool>{"name":"patch_file","args":{"path":"second.txt","old_text":"missing","new_text":"new"}}</tool>',
            "<final>second</final>",
        ]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
    )

    assert agent.ask("first run") == "first"
    assert agent.ask("second run") == "second"

    second_report = json.loads(
        (agent.run_store.run_dir(agent._last_task_state) / "report.json").read_text(encoding="utf-8")
    )
    assert second_report["tool_call_summary"] == {"validation_error": 1}
    assert second_report["changed_files"] == []
    assert second_report["patches_applied"] == 0


def test_report_does_not_count_already_applied_patch_as_new_change(tmp_path):
    (tmp_path / "code.py").write_text("new\n", encoding="utf-8")
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient([
            '<tool>{"name":"patch_file","args":{"path":"code.py","old_text":"old","new_text":"new"}}</tool>',
            "<final>done</final>",
        ]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
    )

    assert agent.ask("patch already applied") == "done"

    report = json.loads(
        (agent.run_store.run_dir(agent._last_task_state) / "report.json").read_text(encoding="utf-8")
    )
    assert report["tool_call_summary"] == {"already_applied": 1}
    assert report["changed_files"] == []
    assert report["patches_applied"] == 0


def test_report_includes_changed_files_for_successful_patch(tmp_path):
    (tmp_path / "code.py").write_text("old\n", encoding="utf-8")
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient([
            '<tool>{"name":"patch_file","args":{"path":"code.py","old_text":"old","new_text":"new"}}</tool>',
            "<final>done</final>",
        ]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
    )

    agent.ask("fix code")

    run_dirs = list((tmp_path / ".mico" / "runs").iterdir())
    report = json.loads((run_dirs[0] / "report.json").read_text(encoding="utf-8"))
    assert report["changed_files"] == ["code.py"]
    assert report["patches_applied"] == 1


def test_report_changed_files_deduplicates_successful_patches(tmp_path):
    (tmp_path / "code.py").write_text("one\n", encoding="utf-8")
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient([
            '<tool>{"name":"patch_file","args":{"path":"code.py","old_text":"one","new_text":"two"}}</tool>',
            '<tool>{"name":"patch_file","args":{"path":"code.py","old_text":"two","new_text":"three"}}</tool>',
            "<final>done</final>",
        ]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
    )

    agent.ask("fix code twice")

    run_dirs = list((tmp_path / ".mico" / "runs").iterdir())
    report = json.loads((run_dirs[0] / "report.json").read_text(encoding="utf-8"))
    assert report["changed_files"] == ["code.py"]
    assert report["patches_applied"] == 2


def test_report_ignores_failed_patch_for_changed_files(tmp_path):
    (tmp_path / "code.py").write_text("old\n", encoding="utf-8")
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient([
            '<tool>{"name":"patch_file","args":{"path":"code.py","old_text":"missing","new_text":"new"}}</tool>',
            "<final>done</final>",
        ]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
    )

    agent.ask("fix code")

    run_dirs = list((tmp_path / ".mico" / "runs").iterdir())
    report = json.loads((run_dirs[0] / "report.json").read_text(encoding="utf-8"))
    assert report["changed_files"] == []
    assert report["patches_applied"] == 0


def test_max_steps_allows_final_after_last_tool(tmp_path):
    (tmp_path / "notes.txt").write_text("hello\n", encoding="utf-8")
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient([
            '<tool>{"name":"read_file","args":{"path":"notes.txt","start":1,"end":80}}</tool>',
            "<final>done</final>",
        ]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
        max_steps=1,
    )

    answer = agent.ask("read file once")

    assert answer == "done"
    run_dirs = list((tmp_path / ".mico" / "runs").iterdir())
    state = json.loads((run_dirs[0] / "state.json").read_text(encoding="utf-8"))
    assert state["tool_steps"] == 1
    assert state["status"] == "success"


def test_max_steps_rejects_extra_tool_after_budget(tmp_path):
    (tmp_path / "a.txt").write_text("aaa\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("bbb\n", encoding="utf-8")
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient([
            '<tool>{"name":"read_file","args":{"path":"a.txt","start":1,"end":80}}</tool>',
            '<tool>{"name":"read_file","args":{"path":"b.txt","start":1,"end":80}}</tool>',
            "<final>done</final>",
        ]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
        max_steps=1,
    )

    answer = agent.ask("read too many files")

    assert answer == "Stopped after reaching the step limit."
    run_dirs = list((tmp_path / ".mico" / "runs").iterdir())
    state = json.loads((run_dirs[0] / "state.json").read_text(encoding="utf-8"))
    assert state["tool_steps"] == 1
    assert state["stop_reason"] == "step_limit"


def test_step_limit_takes_precedence_when_attempt_limit_also_reached(tmp_path):
    (tmp_path / "a.txt").write_text("aaa\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("bbb\n", encoding="utf-8")
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient([
            '<tool>{"name":"read_file","args":{"path":"a.txt","start":1,"end":80}}</tool>',
            "not xml 1",
            "not xml 2",
            '<tool>{"name":"read_file","args":{"path":"b.txt","start":1,"end":80}}</tool>',
        ]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
        max_steps=1,
    )

    answer = agent.ask("read too many files")

    assert answer == "Stopped after reaching the step limit."
    run_dirs = list((tmp_path / ".mico" / "runs").iterdir())
    state = json.loads((run_dirs[0] / "state.json").read_text(encoding="utf-8"))
    report = json.loads((run_dirs[0] / "report.json").read_text(encoding="utf-8"))
    assert state["stop_reason"] == "step_limit"
    assert report["failure_category"] == "step_limit"


def test_model_error_produces_state_trace_report(tmp_path):
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FailingModelClient("boom"),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
    )

    answer = agent.ask("hello")

    assert "Stopped after model error: boom" in answer

    run_dirs = list((tmp_path / ".mico" / "runs").iterdir())
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]

    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "stopped"
    assert state["stop_reason"] == "model_error"

    events = [json.loads(line) for line in (run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    finished = [e for e in events if e["event"] == "run_finished"]
    assert len(finished) == 1
    assert finished[0]["stop_reason"] == "model_error"
    assert "run_duration_ms" in finished[0]

    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    assert report["artifacts_version"] == "1"
    assert report["failure_category"] == "model_error"


def test_success_report_has_artifacts_version_and_failure_category(tmp_path):
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient(["<final>ok</final>"]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
    )

    agent.ask("hello")

    run_dirs = list((tmp_path / ".mico" / "runs").iterdir())
    report = json.loads((run_dirs[0] / "report.json").read_text(encoding="utf-8"))
    assert report["artifacts_version"] == "1"
    assert report["failure_category"] == "success"


def test_step_limit_report_has_correct_failure_category(tmp_path):
    (tmp_path / "a.txt").write_text("aaa\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("bbb\n", encoding="utf-8")
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient([
            '<tool>{"name":"read_file","args":{"path":"a.txt","start":1,"end":80}}</tool>',
            '<tool>{"name":"read_file","args":{"path":"b.txt","start":1,"end":80}}</tool>',
            "<final>done</final>",
        ]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
        max_steps=1,
    )

    agent.ask("read too many files")

    run_dirs = list((tmp_path / ".mico" / "runs").iterdir())
    report = json.loads((run_dirs[0] / "report.json").read_text(encoding="utf-8"))
    assert report["artifacts_version"] == "1"
    assert report["failure_category"] == "step_limit"


def test_retry_limit_report_has_correct_failure_category(tmp_path):
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient(["bad1", "bad2", "bad3", "bad4"]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
        max_steps=1,
    )

    agent.ask("hello")

    run_dirs = list((tmp_path / ".mico" / "runs").iterdir())
    report = json.loads((run_dirs[0] / "report.json").read_text(encoding="utf-8"))
    assert report["artifacts_version"] == "1"
    assert report["failure_category"] == "malformed_model_output"


def test_tool_spec_metadata_patch_file(tmp_path):
    from mico.tools import TOOL_SPECS

    patch = TOOL_SPECS["patch_file"]
    assert patch.requires_approval is True
    assert patch.read_only is False
    assert patch.concurrency_safe is False


def test_tool_spec_metadata_readonly_tools():
    from mico.tools import TOOL_SPECS

    for name in ("list_files", "read_file", "search"):
        spec = TOOL_SPECS[name]
        assert spec.read_only is True, f"{name} should be read_only"
        assert spec.concurrency_safe is True, f"{name} should be concurrency_safe"
        assert spec.requires_approval is False, f"{name} should not require approval"


def test_tool_catalog_includes_new_fields(tmp_path):
    workspace = Workspace.build(tmp_path)
    executor = ToolExecutor(workspace, approval_policy="auto")
    catalog = executor.tool_catalog()

    patch_entry = next(e for e in catalog if e["name"] == "patch_file")
    assert patch_entry["read_only"] is False
    assert patch_entry["concurrency_safe"] is False
    assert "max_result_chars" in patch_entry

    read_entry = next(e for e in catalog if e["name"] == "read_file")
    assert read_entry["read_only"] is True
    assert read_entry["concurrency_safe"] is True


def test_run_store_write_json_is_parseable(tmp_path):
    from mico.state import RunStore

    store = RunStore(tmp_path / "runs")
    path = tmp_path / "runs" / "test.json"
    payload = {"key": "value", "nested": {"a": 1}}
    store._write_json(path, payload)

    assert path.exists()
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded == payload
    # tmp file should not remain
    assert not path.with_suffix(".json.tmp").exists()


def test_approval_denied_then_same_call_is_repeated(tmp_path):
    (tmp_path / "code.py").write_text("old\n", encoding="utf-8")
    workspace = Workspace.build(tmp_path)
    executor = ToolExecutor(workspace, approval_policy="never")
    args = {"path": "code.py", "old_text": "old", "new_text": "new"}

    first = executor.execute("patch_file", args)
    second = executor.execute("patch_file", args)

    assert first.metadata["error_kind"] == "approval_denied"
    assert first.metadata["blocked_by_approval"] is True
    assert second.metadata["error_kind"] == "repeated_call"
    assert second.metadata["repeated_call"] is True


def test_validation_error_then_valid_call_not_repeated(tmp_path):
    (tmp_path / "notes.txt").write_text("hello\n", encoding="utf-8")
    workspace = Workspace.build(tmp_path)
    executor = ToolExecutor(workspace, approval_policy="auto")

    bad = executor.execute("read_file", {"start": 1, "end": 2})
    good = executor.execute("read_file", {"path": "notes.txt", "start": 1, "end": 2})

    assert bad.metadata["error_kind"] == "validation_error"
    assert good.metadata["error_kind"] == "ok"
    assert good.metadata["ok"] is True


def test_execution_validation_error_then_same_call_not_repeated(tmp_path):
    (tmp_path / "code.py").write_text("hello\n", encoding="utf-8")
    workspace = Workspace.build(tmp_path)
    executor = ToolExecutor(workspace, approval_policy="auto")
    args = {"path": "code.py", "old_text": "missing", "new_text": "x"}

    first = executor.execute("patch_file", args)
    second = executor.execute("patch_file", args)

    assert first.metadata["error_kind"] == "validation_error"
    assert second.metadata["error_kind"] == "validation_error"
    assert second.metadata["repeated_call"] is False


def test_success_then_same_call_is_repeated(tmp_path):
    (tmp_path / "notes.txt").write_text("hello\n", encoding="utf-8")
    workspace = Workspace.build(tmp_path)
    executor = ToolExecutor(workspace, approval_policy="auto")
    args = {"path": "notes.txt", "start": 1, "end": 80}

    first = executor.execute("read_file", args)
    second = executor.execute("read_file", args)

    assert first.metadata["error_kind"] == "ok"
    assert second.metadata["error_kind"] == "repeated_call"
    assert second.metadata["repeated_call"] is True


def test_patch_file_reusing_successful_old_text_in_same_file_is_repeated(tmp_path):
    (tmp_path / "code.py").write_text("old\n", encoding="utf-8")
    workspace = Workspace.build(tmp_path)
    executor = ToolExecutor(workspace, approval_policy="auto")

    first = executor.execute("patch_file", {
        "path": "code.py",
        "old_text": "old",
        "new_text": "new",
    })
    second = executor.execute("patch_file", {
        "path": "code.py",
        "old_text": "old",
        "new_text": "better",
    })

    assert first.metadata["error_kind"] == "ok"
    assert second.metadata["error_kind"] == "repeated_call"
    assert second.metadata["repeated_call"] is True
    assert (tmp_path / "code.py").read_text(encoding="utf-8") == "new\n"


def test_patch_file_same_old_text_in_different_files_is_allowed(tmp_path):
    (tmp_path / "first.py").write_text("old\n", encoding="utf-8")
    (tmp_path / "second.py").write_text("old\n", encoding="utf-8")
    workspace = Workspace.build(tmp_path)
    executor = ToolExecutor(workspace, approval_policy="auto")

    first = executor.execute("patch_file", {
        "path": "first.py",
        "old_text": "old",
        "new_text": "new",
    })
    second = executor.execute("patch_file", {
        "path": "second.py",
        "old_text": "old",
        "new_text": "new",
    })

    assert first.metadata["error_kind"] == "ok"
    assert second.metadata["error_kind"] == "ok"
    assert (tmp_path / "first.py").read_text(encoding="utf-8") == "new\n"
    assert (tmp_path / "second.py").read_text(encoding="utf-8") == "new\n"


def test_patch_file_can_continue_from_current_content(tmp_path):
    (tmp_path / "code.py").write_text("old\n", encoding="utf-8")
    workspace = Workspace.build(tmp_path)
    executor = ToolExecutor(workspace, approval_policy="auto")

    first = executor.execute("patch_file", {
        "path": "code.py",
        "old_text": "old",
        "new_text": "new",
    })
    second = executor.execute("patch_file", {
        "path": "code.py",
        "old_text": "new",
        "new_text": "final",
    })

    assert first.metadata["error_kind"] == "ok"
    assert second.metadata["error_kind"] == "ok"
    assert (tmp_path / "code.py").read_text(encoding="utf-8") == "final\n"


def test_patch_file_consumed_old_text_state_resets_between_runs(tmp_path):
    (tmp_path / "code.py").write_text("old\n", encoding="utf-8")
    workspace = Workspace.build(tmp_path)
    executor = ToolExecutor(workspace, approval_policy="auto")

    first = executor.execute("patch_file", {
        "path": "code.py",
        "old_text": "old",
        "new_text": "new",
    })
    executor.reset_run_state()
    second = executor.execute("patch_file", {
        "path": "code.py",
        "old_text": "old",
        "new_text": "new",
    })

    assert first.metadata["error_kind"] == "ok"
    assert second.metadata["error_kind"] == "already_applied"
    assert second.metadata["repeated_call"] is False


def test_long_tool_result_clipped_in_history(tmp_path):
    long_content = "x" * 5000
    (tmp_path / "big.txt").write_text(long_content + "\n", encoding="utf-8")
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient([
            '<tool>{"name":"read_file","args":{"path":"big.txt","start":1,"end":1}}</tool>',
            "<final>done</final>",
        ]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
    )

    answer = agent.ask("read big file")

    assert answer == "done"
    tool_entry = agent.history[1]
    assert tool_entry["role"] == "tool"
    assert len(tool_entry["content"]) <= 4000
    assert tool_entry["content"].endswith("...")


def test_model_requested_trace_has_prompt_metadata(tmp_path):
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient(["<final>ok</final>"]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
    )

    agent.ask("hello")

    events = _trace_events(tmp_path / ".mico" / "runs")
    requested = [e for e in events if e["event"] == "model_requested"]
    assert len(requested) >= 1
    event = requested[0]
    assert "prompt_metadata" in event
    meta = event["prompt_metadata"]
    assert "prompt_chars" in meta
    assert "history_items_total" in meta
    assert "history_items_used" in meta
    assert "tool_count" in meta
    assert "restricted_tool_count" in meta
    assert "approval_policy" in meta
    assert "current_request_chars" in meta
    assert isinstance(meta["prompt_chars"], int)
    assert meta["prompt_chars"] > 0


def test_model_requested_trace_does_not_contain_full_prompt(tmp_path):
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient(["<final>ok</final>"]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
    )

    agent.ask("this is a unique request xyz789")

    events = _trace_events(tmp_path / ".mico" / "runs")
    requested = [e for e in events if e["event"] == "model_requested"]
    assert len(requested) >= 1
    event_json = json.dumps(requested[0])
    assert "this is a unique request xyz789" not in event_json
    assert "You are mico" not in event_json


def test_report_has_prompt_metadata(tmp_path):
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient(["<final>ok</final>"]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
    )

    agent.ask("hello")

    run_dirs = list((tmp_path / ".mico" / "runs").iterdir())
    report = json.loads((run_dirs[0] / "report.json").read_text(encoding="utf-8"))
    assert "prompt_metadata" in report
    meta = report["prompt_metadata"]
    assert "prompt_chars" in meta
    assert "tool_count" in meta
    assert "approval_policy" in meta


def test_report_preserves_existing_fields_with_prompt_metadata(tmp_path):
    (tmp_path / "code.py").write_text("hello\n", encoding="utf-8")
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient([
            '<tool>{"name":"patch_file","args":{"path":"code.py","old_text":"hello","new_text":"x"}}</tool>',
            "<final>done</final>",
        ]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
        approval_policy="never",
    )

    agent.ask("fix code")

    run_dirs = list((tmp_path / ".mico" / "runs").iterdir())
    report = json.loads((run_dirs[0] / "report.json").read_text(encoding="utf-8"))
    assert report["artifacts_version"] == "1"
    assert report["failure_category"] == "success"
    assert "prompt_metadata" in report
    assert report["prompt_metadata"]["approval_policy"] == "never"
    assert report["prompt_metadata"]["restricted_tool_count"] == 3


def test_model_parsed_trace_has_error_kind_on_retry(tmp_path):
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient(["not xml", "<final>done</final>"]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
    )

    agent.ask("hello")

    events = _trace_events(tmp_path / ".mico" / "runs")
    parsed_events = [e for e in events if e["event"] == "model_parsed"]
    assert len(parsed_events) >= 2
    retry_event = parsed_events[0]
    assert retry_event["kind"] == "retry"
    assert retry_event["error_kind"] == "unknown_block"
    final_event = parsed_events[1]
    assert final_event["kind"] == "final"
    assert "error_kind" not in final_event


def test_model_parsed_trace_error_kind_malformed_tool_json(tmp_path):
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient(["<tool>{bad</tool>", "<final>done</final>"]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
    )

    agent.ask("hello")

    events = _trace_events(tmp_path / ".mico" / "runs")
    parsed_events = [e for e in events if e["event"] == "model_parsed"]
    retry_event = parsed_events[0]
    assert retry_event["kind"] == "retry"
    assert retry_event["error_kind"] == "malformed_tool_json"


def test_model_parsed_trace_error_kind_empty_final(tmp_path):
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient(["<final>  </final>", "<final>done</final>"]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
    )

    agent.ask("hello")

    events = _trace_events(tmp_path / ".mico" / "runs")
    parsed_events = [e for e in events if e["event"] == "model_parsed"]
    retry_event = parsed_events[0]
    assert retry_event["kind"] == "retry"
    assert retry_event["error_kind"] == "empty_final"


def test_retry_limit_report_has_parser_error_kind(tmp_path):
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient(["bad1", "bad2", "bad3", "bad4"]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
        max_steps=1,
    )

    agent.ask("hello")

    run_dirs = list((tmp_path / ".mico" / "runs").iterdir())
    report = json.loads((run_dirs[0] / "report.json").read_text(encoding="utf-8"))
    assert report["failure_category"] == "malformed_model_output"
    assert "parser_error_kind" in report
    assert report["parser_error_kind"] == "unknown_block"


def test_report_parser_error_kind_not_present_on_success(tmp_path):
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient(["<final>ok</final>"]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
    )

    agent.ask("hello")

    run_dirs = list((tmp_path / ".mico" / "runs").iterdir())
    report = json.loads((run_dirs[0] / "report.json").read_text(encoding="utf-8"))
    assert "parser_error_kind" not in report


def test_parser_error_kind_resets_between_asks(tmp_path):
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient(["bad1", "bad2", "bad3", "bad4", "<final>ok</final>"]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
        max_steps=1,
    )

    first = agent.ask("first")
    second = agent.ask("second")

    assert first == "Stopped after too many malformed model responses."
    assert second == "ok"
    reports = [
        json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
        for run_dir in (tmp_path / ".mico" / "runs").iterdir()
    ]
    retry_report = next(report for report in reports if report["task_state"]["stop_reason"] == "retry_limit")
    success_report = next(report for report in reports if report["task_state"]["stop_reason"] == "final")
    assert retry_report["parser_error_kind"] == "unknown_block"
    assert "parser_error_kind" not in success_report


def test_agent_loop_executes_write_file(tmp_path):
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient([
            '<tool>{"name":"write_file","args":{"path":"out.txt","content":"hello mico"}}</tool>',
            "<final>written</final>",
        ]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
    )

    answer = agent.ask("create file")

    assert answer == "written"
    assert (tmp_path / "out.txt").read_text(encoding="utf-8") == "hello mico"
    assert agent.history[1]["role"] == "tool"
    assert agent.history[1]["name"] == "write_file"
    assert agent.history[1]["metadata"]["ok"] is True


def test_agent_loop_executes_run_command(tmp_path):
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient([
            '<tool>{"name":"run_command","args":{"argv":["python","-c","print(42)"]}}</tool>',
            "<final>ran</final>",
        ]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
    )

    answer = agent.ask("run python")

    assert answer == "ran"
    assert agent.history[1]["role"] == "tool"
    assert agent.history[1]["name"] == "run_command"
    assert agent.history[1]["metadata"]["ok"] is True
    assert "42" in agent.history[1]["content"]


def test_agent_loop_run_command_failure_records_exit_code(tmp_path):
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient([
            '<tool>{"name":"run_command","args":{"argv":["python","-c","import sys; sys.exit(2)"]}}</tool>',
            "<final>failed</final>",
        ]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
    )

    answer = agent.ask("run failing cmd")

    assert answer == "failed"
    assert agent.history[1]["metadata"]["ok"] is False
    assert agent.history[1]["metadata"]["error_kind"] == "command_failed"
    assert agent.history[1]["metadata"]["exit_code"] == 2
    assert agent.history[1]["metadata"]["timed_out"] is False


def test_agent_loop_write_file_rejected_by_approval_never(tmp_path):
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient([
            '<tool>{"name":"write_file","args":{"path":"out.txt","content":"hello"}}</tool>',
            "<final>done</final>",
        ]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
        approval_policy="never",
    )

    answer = agent.ask("create file")

    assert answer == "done"
    assert "not allowed" in agent.history[1]["content"]
    assert agent.history[1]["metadata"]["error_kind"] == "approval_denied"
    assert agent.history[1]["metadata"]["blocked_by_approval"] is True
    assert not (tmp_path / "out.txt").exists()


def test_agent_loop_run_command_rejected_by_approval_never(tmp_path):
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient([
            '<tool>{"name":"run_command","args":{"argv":["python","-c","print(1)"]}}</tool>',
            "<final>done</final>",
        ]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
        approval_policy="never",
    )

    answer = agent.ask("run cmd")

    assert answer == "done"
    assert "not allowed" in agent.history[1]["content"]
    assert agent.history[1]["metadata"]["error_kind"] == "approval_denied"
    assert agent.history[1]["metadata"]["blocked_by_approval"] is True


def test_report_includes_write_file_in_changed_files(tmp_path):
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient([
            '<tool>{"name":"write_file","args":{"path":"new.txt","content":"data"}}</tool>',
            "<final>done</final>",
        ]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
    )

    agent.ask("create file")

    run_dirs = list((tmp_path / ".mico" / "runs").iterdir())
    report = json.loads((run_dirs[0] / "report.json").read_text(encoding="utf-8"))
    assert "new.txt" in report["changed_files"]


def test_report_tool_call_summary_counts_write_file_ok(tmp_path):
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient([
            '<tool>{"name":"write_file","args":{"path":"out.txt","content":"x"}}</tool>',
            "<final>done</final>",
        ]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
    )

    agent.ask("write")

    run_dirs = list((tmp_path / ".mico" / "runs").iterdir())
    report = json.loads((run_dirs[0] / "report.json").read_text(encoding="utf-8"))
    assert report["tool_call_summary"]["ok"] == 1


def test_report_tool_call_summary_counts_run_command_ok(tmp_path):
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient([
            '<tool>{"name":"run_command","args":{"argv":["python","-c","print(1)"]}}</tool>',
            "<final>done</final>",
        ]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
    )

    agent.ask("run")

    run_dirs = list((tmp_path / ".mico" / "runs").iterdir())
    report = json.loads((run_dirs[0] / "report.json").read_text(encoding="utf-8"))
    assert report["tool_call_summary"]["ok"] == 1


def test_report_tool_call_summary_counts_approval_denied_for_both_tools(tmp_path):
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient([
            '<tool>{"name":"write_file","args":{"path":"out.txt","content":"x"}}</tool>',
            '<tool>{"name":"run_command","args":{"argv":["python","-c","print(1)"]}}</tool>',
            "<final>done</final>",
        ]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
        approval_policy="never",
    )

    agent.ask("write and run")

    run_dirs = list((tmp_path / ".mico" / "runs").iterdir())
    report = json.loads((run_dirs[0] / "report.json").read_text(encoding="utf-8"))
    assert report["tool_call_summary"]["approval_denied"] == 2


def test_prompt_includes_write_file_and_run_command(tmp_path):
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient(),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
    )

    prompt = agent.build_prompt("do something")

    assert "write_file" in prompt
    assert "run_command" in prompt


def test_report_available_tools_includes_new_tools(tmp_path):
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient(["<final>ok</final>"]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
    )

    agent.ask("hello")

    run_dirs = list((tmp_path / ".mico" / "runs").iterdir())
    report = json.loads((run_dirs[0] / "report.json").read_text(encoding="utf-8"))
    assert "write_file" in report["available_tools"]
    assert "run_command" in report["available_tools"]


def test_report_restricted_tools_includes_new_tools_under_approval_never(tmp_path):
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient(["<final>ok</final>"]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
        approval_policy="never",
    )

    agent.ask("hello")

    run_dirs = list((tmp_path / ".mico" / "runs").iterdir())
    report = json.loads((run_dirs[0] / "report.json").read_text(encoding="utf-8"))
    assert "write_file" in report["restricted_tools"]
    assert "run_command" in report["restricted_tools"]


def test_report_does_not_contain_raw_model_output(tmp_path):
    workspace = Workspace.build(tmp_path)
    raw_text = "RAW_MODEL_OUTPUT_SECRET_12345"
    agent = Mico(
        model_client=FakeModelClient([raw_text, "<final>done</final>"]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
    )

    agent.ask("hello")

    run_dirs = list((tmp_path / ".mico" / "runs").iterdir())
    report_text = (run_dirs[0] / "report.json").read_text(encoding="utf-8")
    assert raw_text not in report_text


def test_report_includes_files_written_for_write_file(tmp_path):
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient([
            '<tool>{"name":"write_file","args":{"path":"out.txt","content":"data"}}</tool>',
            "<final>done</final>",
        ]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
    )

    agent.ask("create file")

    run_dirs = list((tmp_path / ".mico" / "runs").iterdir())
    report = json.loads((run_dirs[0] / "report.json").read_text(encoding="utf-8"))
    assert "files_written" in report
    assert report["files_written"] == ["out.txt"]


def test_report_files_written_empty_when_no_write_file(tmp_path):
    (tmp_path / "a.txt").write_text("hello\n", encoding="utf-8")
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient([
            '<tool>{"name":"read_file","args":{"path":"a.txt","start":1,"end":80}}</tool>',
            "<final>done</final>",
        ]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
    )

    agent.ask("read file")

    run_dirs = list((tmp_path / ".mico" / "runs").iterdir())
    report = json.loads((run_dirs[0] / "report.json").read_text(encoding="utf-8"))
    assert report["files_written"] == []


def test_report_commands_run_contains_run_command_metadata(tmp_path):
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient([
            '<tool>{"name":"run_command","args":{"argv":["python","-c","print(42)"]}}</tool>',
            "<final>done</final>",
        ]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
    )

    agent.ask("run python")

    run_dirs = list((tmp_path / ".mico" / "runs").iterdir())
    report = json.loads((run_dirs[0] / "report.json").read_text(encoding="utf-8"))
    assert "commands_run" in report
    assert len(report["commands_run"]) == 1
    cmd = report["commands_run"][0]
    assert cmd["argv"] == ["python", "-c", "print(42)"]
    assert cmd["exit_code"] == 0
    assert cmd["timed_out"] is False
    assert isinstance(cmd["duration_ms"], int)
    assert cmd["duration_ms"] >= 0
    assert "42" in cmd["stdout_tail"]
    assert cmd["ok"] is True
    assert cmd["error_kind"] == "ok"


def test_report_commands_run_captures_failure(tmp_path):
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient([
            '<tool>{"name":"run_command","args":{"argv":["python","-c","import sys; sys.exit(2)"]}}</tool>',
            "<final>done</final>",
        ]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
    )

    agent.ask("run failing cmd")

    run_dirs = list((tmp_path / ".mico" / "runs").iterdir())
    report = json.loads((run_dirs[0] / "report.json").read_text(encoding="utf-8"))
    assert len(report["commands_run"]) == 1
    cmd = report["commands_run"][0]
    assert cmd["exit_code"] == 2
    assert cmd["ok"] is False
    assert cmd["error_kind"] == "command_failed"


def test_report_commands_run_empty_when_no_run_command(tmp_path):
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient([
            '<tool>{"name":"write_file","args":{"path":"out.txt","content":"x"}}</tool>',
            "<final>done</final>",
        ]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
    )

    agent.ask("write file")

    run_dirs = list((tmp_path / ".mico" / "runs").iterdir())
    report = json.loads((run_dirs[0] / "report.json").read_text(encoding="utf-8"))
    assert report["commands_run"] == []


def test_report_commands_run_empty_under_approval_never(tmp_path):
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient([
            '<tool>{"name":"run_command","args":{"argv":["python","-c","print(1)"]}}</tool>',
            "<final>done</final>",
        ]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
        approval_policy="never",
    )

    agent.ask("run cmd")

    run_dirs = list((tmp_path / ".mico" / "runs").iterdir())
    report = json.loads((run_dirs[0] / "report.json").read_text(encoding="utf-8"))
    assert report["commands_run"] == []


def test_report_verification_summary_present_with_verify(tmp_path):
    from mico.verification import VerificationResult

    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient(["<final>ok</final>"]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
    )

    agent.ask("hello")

    verification_result = VerificationResult(
        command="python verify.py",
        argv=["python", "verify.py"],
        ok=True,
        exit_code=0,
        duration_ms=150,
        timed_out=False,
        stdout_tail="ALL TESTS PASSED",
        stderr_tail="",
    )
    run_dirs = list((tmp_path / ".mico" / "runs").iterdir())
    report = agent.build_report(agent._last_task_state, verification_result=verification_result)
    assert "verification_summary" in report
    summary = report["verification_summary"]
    assert summary["ok"] is True
    assert summary["exit_code"] == 0
    assert summary["timed_out"] is False
    assert summary["duration_ms"] == 150
    assert summary["argv"] == ["python", "verify.py"]
    assert summary["stdout_tail"] == "ALL TESTS PASSED"
    assert summary["stderr_tail"] == ""


def test_report_verification_summary_absent_without_verify(tmp_path):
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient(["<final>ok</final>"]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
    )

    agent.ask("hello")

    run_dirs = list((tmp_path / ".mico" / "runs").iterdir())
    report = json.loads((run_dirs[0] / "report.json").read_text(encoding="utf-8"))
    assert "verification_summary" not in report


def test_report_preserves_legacy_verification_fields_with_summary(tmp_path):
    from mico.verification import VerificationResult

    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient(["<final>ok</final>"]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
    )

    agent.ask("hello")

    verification_result = VerificationResult(
        command="python verify.py",
        argv=["python", "verify.py"],
        ok=False,
        exit_code=1,
        duration_ms=200,
        timed_out=False,
        stdout_tail="FAIL",
        stderr_tail="AssertionError",
    )
    report = agent.build_report(agent._last_task_state, verification_result=verification_result)
    # Legacy fields still present
    assert report["verification_ok"] is False
    assert report["verification_exit_code"] == 1
    assert report["verification_timed_out"] is False
    # New summary also present
    assert "verification_summary" in report
    assert report["verification_summary"]["ok"] is False


def test_report_files_written_deduplicates_multiple_writes(tmp_path):
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient([
            '<tool>{"name":"write_file","args":{"path":"out.txt","content":"v1"}}</tool>',
            '<tool>{"name":"write_file","args":{"path":"out.txt","content":"v2"}}</tool>',
            "<final>done</final>",
        ]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
    )

    agent.ask("write twice")

    run_dirs = list((tmp_path / ".mico" / "runs").iterdir())
    report = json.loads((run_dirs[0] / "report.json").read_text(encoding="utf-8"))
    assert report["files_written"] == ["out.txt"]
    assert report["changed_files"] == ["out.txt"]


# --- approval=ask tests ---

def test_approval_ask_patch_file_auto_executes(tmp_path):
    (tmp_path / "code.py").write_text("old\n", encoding="utf-8")
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient([
            '<tool>{"name":"patch_file","args":{"path":"code.py","old_text":"old","new_text":"new"}}</tool>',
            "<final>done</final>",
        ]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
        approval_policy="ask",
    )

    answer = agent.ask("fix code")

    assert answer == "done"
    assert (tmp_path / "code.py").read_text(encoding="utf-8") == "new\n"
    assert agent.history[1]["metadata"]["ok"] is True


def test_approval_ask_write_file_auto_executes(tmp_path):
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient([
            '<tool>{"name":"write_file","args":{"path":"out.txt","content":"hello"}}</tool>',
            "<final>done</final>",
        ]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
        approval_policy="ask",
    )

    answer = agent.ask("create file")

    assert answer == "done"
    assert (tmp_path / "out.txt").read_text(encoding="utf-8") == "hello"
    assert agent.history[1]["metadata"]["ok"] is True


def test_approval_ask_normal_run_command_auto_executes(tmp_path):
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient([
            '<tool>{"name":"run_command","args":{"argv":["python","-c","print(42)"]}}</tool>',
            "<final>done</final>",
        ]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
        approval_policy="ask",
    )

    answer = agent.ask("run python")

    assert answer == "done"
    assert agent.history[1]["metadata"]["ok"] is True
    assert "42" in agent.history[1]["content"]


def test_approval_ask_shell_command_approved_by_callback(tmp_path):
    from mico.prompt import detect_available_shells

    available = detect_available_shells()
    if not available:
        pytest.skip("no shell interpreter available on this platform")

    shell = available[0]
    if shell in ("cmd", "cmd.exe"):
        argv = [shell, "/c", "echo hello"]
    else:
        argv = [shell, "-c", "echo hello"]

    workspace = Workspace.build(tmp_path)
    always_approve = lambda argv: True
    agent = Mico(
        model_client=FakeModelClient([
            f'<tool>{{"name":"run_command","args":{{"argv":{json.dumps(argv)}}}}}</tool>',
            "<final>done</final>",
        ]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
        approval_policy="ask",
        approval_callback=always_approve,
    )

    answer = agent.ask("run shell command")

    assert answer == "done"
    assert agent.history[1]["metadata"]["ok"] is True
    assert agent.history[1]["metadata"]["error_kind"] == "ok"
    assert "hello" in agent.history[1]["content"]


def test_approval_ask_shell_command_denied_by_callback(tmp_path):
    workspace = Workspace.build(tmp_path)
    always_deny = lambda argv: False
    agent = Mico(
        model_client=FakeModelClient([
            '<tool>{"name":"run_command","args":{"argv":["cmd","/c","echo hello"]}}</tool>',
            "<final>done</final>",
        ]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
        approval_policy="ask",
        approval_callback=always_deny,
    )

    answer = agent.ask("run cmd")

    assert answer == "done"
    assert agent.history[1]["metadata"]["ok"] is False
    assert agent.history[1]["metadata"]["error_kind"] == "approval_denied"


def test_approval_ask_shell_command_denied_not_in_commands_run(tmp_path):
    workspace = Workspace.build(tmp_path)
    always_deny = lambda argv: False
    agent = Mico(
        model_client=FakeModelClient([
            '<tool>{"name":"run_command","args":{"argv":["cmd","/c","echo hello"]}}</tool>',
            "<final>done</final>",
        ]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
        approval_policy="ask",
        approval_callback=always_deny,
    )

    agent.ask("run cmd")

    run_dirs = list((tmp_path / ".mico" / "runs").iterdir())
    report = json.loads((run_dirs[0] / "report.json").read_text(encoding="utf-8"))
    assert report["commands_run"] == []
    assert report["tool_call_summary"]["approval_denied"] == 1


def test_approval_ask_shell_command_approved_in_commands_run(tmp_path):
    """Shell interpreter command approved via callback actually executes and appears in report."""
    from mico.prompt import detect_available_shells

    available = detect_available_shells()
    if not available:
        pytest.skip("no shell interpreter available on this platform")

    shell = available[0]
    if shell in ("cmd", "cmd.exe"):
        argv = [shell, "/c", "echo hello"]
    else:
        argv = [shell, "-c", "echo hello"]

    workspace = Workspace.build(tmp_path)
    always_approve = lambda argv: True
    agent = Mico(
        model_client=FakeModelClient([
            f'<tool>{{"name":"run_command","args":{{"argv":{json.dumps(argv)}}}}}</tool>',
            "<final>done</final>",
        ]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
        approval_policy="ask",
        approval_callback=always_approve,
    )

    agent.ask("run shell command")

    assert agent.history[1]["metadata"]["ok"] is True
    assert agent.history[1]["metadata"]["error_kind"] == "ok"

    run_dirs = list((tmp_path / ".mico" / "runs").iterdir())
    report = json.loads((run_dirs[0] / "report.json").read_text(encoding="utf-8"))
    assert len(report["commands_run"]) == 1
    cmd = report["commands_run"][0]
    assert cmd["argv"][0] == shell
    assert "hello" in cmd["stdout_tail"]
    assert cmd["error_kind"] == "ok"


def test_approval_ask_no_callback_shell_command_denied(tmp_path):
    """Without a callback, shell commands under approval=ask should be denied."""
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient([
            '<tool>{"name":"run_command","args":{"argv":["cmd","/c","dir"]}}</tool>',
            "<final>done</final>",
        ]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
        approval_policy="ask",
    )

    answer = agent.ask("run cmd")

    assert answer == "done"
    assert agent.history[1]["metadata"]["ok"] is False
    assert agent.history[1]["metadata"]["error_kind"] == "approval_denied"


def test_approval_ask_readonly_tools_work(tmp_path):
    (tmp_path / "notes.txt").write_text("hello\n", encoding="utf-8")
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient([
            '<tool>{"name":"read_file","args":{"path":"notes.txt","start":1,"end":80}}</tool>',
            "<final>done</final>",
        ]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
        approval_policy="ask",
    )

    answer = agent.ask("read file")

    assert answer == "done"
    assert "hello" in agent.history[1]["content"]
    assert agent.history[1]["metadata"]["ok"] is True


def test_approval_ask_denied_shell_command_repeated(tmp_path):
    """Denied shell commands are caught by repeated_call on retry."""
    workspace = Workspace.build(tmp_path)
    always_deny = lambda argv: False
    agent = Mico(
        model_client=FakeModelClient([
            '<tool>{"name":"run_command","args":{"argv":["cmd","/c","dir"]}}</tool>',
            '<tool>{"name":"run_command","args":{"argv":["cmd","/c","dir"]}}</tool>',
            "<final>done</final>",
        ]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
        approval_policy="ask",
        approval_callback=always_deny,
    )

    answer = agent.ask("run cmd twice")

    assert answer == "done"
    assert agent.history[1]["metadata"]["error_kind"] == "approval_denied"
    assert agent.history[2]["metadata"]["error_kind"] == "repeated_call"


# --- UI event callback tests ---


def test_event_callback_receives_tool_started_and_finished(tmp_path):
    (tmp_path / "notes.txt").write_text("hello\n", encoding="utf-8")
    workspace = Workspace.build(tmp_path)
    events = []

    agent = Mico(
        model_client=FakeModelClient([
            '<tool>{"name":"read_file","args":{"path":"notes.txt","start":1,"end":80}}</tool>',
            "<final>done</final>",
        ]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
        event_callback=lambda etype, payload: events.append((etype, dict(payload or {}))),
    )

    agent.ask("read file")

    tool_started = [e for e in events if e[0] == "tool_started"]
    tool_finished = [e for e in events if e[0] == "tool_finished"]
    assert len(tool_started) == 1
    assert len(tool_finished) == 1
    assert tool_started[0][1]["name"] == "read_file"
    assert "path" in tool_started[0][1].get("args", {})
    assert tool_finished[0][1]["name"] == "read_file"
    assert tool_finished[0][1]["ok"] is True


def test_event_callback_receives_retry_on_malformed_output(tmp_path):
    workspace = Workspace.build(tmp_path)
    events = []

    agent = Mico(
        model_client=FakeModelClient(["not xml", "<final>done</final>"]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
        event_callback=lambda etype, payload: events.append((etype, dict(payload or {}))),
    )

    agent.ask("hello")

    retry_events = [e for e in events if e[0] == "retry"]
    assert len(retry_events) == 1
    assert "error_kind" in retry_events[0][1]


def test_event_callback_receives_run_finished(tmp_path):
    workspace = Workspace.build(tmp_path)
    events = []

    agent = Mico(
        model_client=FakeModelClient(["<final>all done</final>"]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
        event_callback=lambda etype, payload: events.append((etype, dict(payload or {}))),
    )

    agent.ask("hello")

    final_events = [e for e in events if e[0] == "run_finished"]
    assert len(final_events) == 1
    assert "final_summary" in final_events[0][1]


def test_event_callback_receives_thinking(tmp_path):
    (tmp_path / "notes.txt").write_text("hello\n", encoding="utf-8")
    workspace = Workspace.build(tmp_path)
    events = []

    agent = Mico(
        model_client=FakeModelClient([
            '<tool>{"name":"read_file","args":{"path":"notes.txt","start":1,"end":80}}</tool>',
            "<final>done</final>",
        ]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
        event_callback=lambda etype, payload: events.append((etype, dict(payload or {}))),
    )

    agent.ask("read file")

    thinking_events = [e for e in events if e[0] == "thinking"]
    assert len(thinking_events) >= 1


def test_event_callback_exception_does_not_break_agent(tmp_path):
    workspace = Workspace.build(tmp_path)
    called = []

    def bad_callback(etype, payload):
        called.append(etype)
        if etype == "thinking":
            raise RuntimeError("boom")

    agent = Mico(
        model_client=FakeModelClient(["<final>ok</final>"]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
        event_callback=bad_callback,
    )

    answer = agent.ask("hello")
    assert answer == "ok"
    assert "thinking" in called
    assert "run_finished" in called


def test_event_callback_not_called_when_none(tmp_path):
    workspace = Workspace.build(tmp_path)

    agent = Mico(
        model_client=FakeModelClient(["<final>ok</final>"]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
    )

    answer = agent.ask("hello")
    assert answer == "ok"


def test_event_callback_tool_finished_includes_error_info(tmp_path):
    (tmp_path / "code.py").write_text("old\n", encoding="utf-8")
    workspace = Workspace.build(tmp_path)
    events = []

    agent = Mico(
        model_client=FakeModelClient([
            '<tool>{"name":"patch_file","args":{"path":"code.py","old_text":"notfound","new_text":"x"}}</tool>',
            "<final>done</final>",
        ]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
        event_callback=lambda etype, payload: events.append((etype, dict(payload or {}))),
        approval_policy="auto",
    )

    agent.ask("fix code")

    finished = [e for e in events if e[0] == "tool_finished"]
    assert len(finished) == 1
    assert finished[0][1]["name"] == "patch_file"
    assert finished[0][1]["ok"] is False
    assert "error_kind" in finished[0][1]


def test_event_callback_tool_args_not_contain_full_content(tmp_path):
    (tmp_path / "code.py").write_text("old content\n", encoding="utf-8")
    workspace = Workspace.build(tmp_path)
    events = []

    agent = Mico(
        model_client=FakeModelClient([
            '<tool>{"name":"patch_file","args":{"path":"code.py","old_text":"old content","new_text":"new content"}}</tool>',
            "<final>done</final>",
        ]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
        event_callback=lambda etype, payload: events.append((etype, dict(payload or {}))),
    )

    agent.ask("fix code")

    started = [e for e in events if e[0] == "tool_started"]
    assert len(started) == 1
    args_str = json.dumps(started[0][1].get("args", {}))
    assert "old content" not in args_str
    assert "new content" not in args_str


def test_event_callback_tool_finished_run_command_has_exit_and_duration(tmp_path):
    workspace = Workspace.build(tmp_path)
    events = []

    agent = Mico(
        model_client=FakeModelClient([
            '<tool>{"name":"run_command","args":{"argv":["python","-c","print(42)"]}}</tool>',
            "<final>done</final>",
        ]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
        event_callback=lambda etype, payload: events.append((etype, dict(payload or {}))),
    )

    agent.ask("run python")

    finished = [e for e in events if e[0] == "tool_finished"]
    assert len(finished) == 1
    assert finished[0][1]["name"] == "run_command"
    assert "exit_code" in finished[0][1]
    assert "duration_ms" in finished[0][1]
    assert finished[0][1]["exit_code"] == 0
    assert finished[0][1]["timed_out"] is False


def test_event_callback_redacts_sensitive_values(tmp_path, monkeypatch):
    monkeypatch.setenv("MY_SECRET", "secret-value-xyz")
    (tmp_path / "notes.txt").write_text("hello\n", encoding="utf-8")
    workspace = Workspace.build(tmp_path)
    events = []

    agent = Mico(
        model_client=FakeModelClient([
            '<tool>{"name":"search","args":{"pattern":"secret-value-xyz","path":"."}}</tool>',
            "<final>done</final>",
        ]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
        event_callback=lambda etype, payload: events.append((etype, dict(payload or {}))),
    )

    agent.ask("search for secret")

    started = [e for e in events if e[0] == "tool_started"]
    assert len(started) == 1
    payload_text = json.dumps(started[0][1])
    assert "secret-value-xyz" not in payload_text
    assert "[REDACTED]" in payload_text


def test_event_callback_redacts_sensitive_values_in_run_command_argv(tmp_path, monkeypatch):
    monkeypatch.setenv("MY_TOKEN", "token-abc-123")
    workspace = Workspace.build(tmp_path)
    events = []

    agent = Mico(
        model_client=FakeModelClient([
            '<tool>{"name":"run_command","args":{"argv":["python","-c","print(\\"token-abc-123\\")"]}}</tool>',
            "<final>done</final>",
        ]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
        event_callback=lambda etype, payload: events.append((etype, dict(payload or {}))),
    )

    agent.ask("run with token")

    started = [e for e in events if e[0] == "tool_started"]
    assert len(started) == 1
    payload_text = json.dumps(started[0][1])
    assert "token-abc-123" not in payload_text
    assert "[REDACTED]" in payload_text


# --- session memory integration tests ---


def test_session_memory_saved_after_read_file(tmp_path):
    (tmp_path / "notes.txt").write_text("hello mico\nbye\n", encoding="utf-8")
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient([
            '<tool>{"name":"read_file","args":{"path":"notes.txt","start":1,"end":80}}</tool>',
            "<final>done</final>",
        ]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
    )

    agent.ask("read file")

    session_path = tmp_path / ".mico" / "sessions" / "default.json"
    assert session_path.exists()
    data = json.loads(session_path.read_text(encoding="utf-8"))
    assert data["session_id"] == "default"
    mem = data["memory"]
    assert mem["task_summary"] == "read file"
    assert "notes.txt" in mem["recent_files"]
    assert "notes.txt" in mem["file_summaries"]
    assert len(mem["episodic_notes"]) > 0


def test_session_memory_loaded_by_new_mico_instance(tmp_path):
    (tmp_path / "code.py").write_text("hello\n", encoding="utf-8")
    workspace = Workspace.build(tmp_path)
    run_store = RunStore(tmp_path / ".mico" / "runs")
    session_store = SessionStore(tmp_path / ".mico" / "sessions")

    first = Mico(
        model_client=FakeModelClient([
            '<tool>{"name":"read_file","args":{"path":"code.py","start":1,"end":80}}</tool>',
            '<final>first run</final>',
        ]),
        workspace=workspace,
        run_store=run_store,
        session_store=session_store,
    )
    first.ask("first task")

    second = Mico(
        model_client=FakeModelClient([
            '<final>second</final>',
        ]),
        workspace=workspace,
        run_store=run_store,
        session_store=session_store,
    )
    assert second.session_memory.task_summary == "first task"
    assert "code.py" in second.session_memory.recent_files
    assert second.ask("second task") == "second"
