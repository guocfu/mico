import json

from mico.providers import FakeModelClient
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


def test_approval_denied_then_same_call_still_denied(tmp_path):
    (tmp_path / "code.py").write_text("old\n", encoding="utf-8")
    workspace = Workspace.build(tmp_path)
    executor = ToolExecutor(workspace, approval_policy="never")
    args = {"path": "code.py", "old_text": "old", "new_text": "new"}

    first = executor.execute("patch_file", args)
    second = executor.execute("patch_file", args)

    assert first.metadata["error_kind"] == "approval_denied"
    assert first.metadata["blocked_by_approval"] is True
    assert second.metadata["error_kind"] == "approval_denied"
    assert second.metadata["blocked_by_approval"] is True


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
    assert report["prompt_metadata"]["restricted_tool_count"] == 1


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
