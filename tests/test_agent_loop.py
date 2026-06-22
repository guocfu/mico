from mico.providers import FakeModelClient
from mico.runtime import Mico
from mico.state import RunStore
from mico.tool_executor import ToolExecutor
from mico.workspace import Workspace


def test_readonly_tool_allowed_under_approval_never(tmp_path):
    (tmp_path / "notes.txt").write_text("hello mico\nbye\n", encoding="utf-8")
    workspace = Workspace.build(tmp_path)
    executor = ToolExecutor(workspace, approval_policy="never")

    result = executor.execute("search", {"pattern": "mico", "path": "."})

    assert result.metadata["ok"] is True
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
