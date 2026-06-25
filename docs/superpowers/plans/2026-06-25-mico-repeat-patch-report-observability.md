# Mico Repeat Patch Report Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:test-driven-development` before production-code edits, then use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix repeat patch behavior, current-run report accuracy, and REPL run-log discoverability for mico.

**Architecture:** Keep the existing agent loop and XML/tool protocol. Add a narrow idempotency guard in `patch_file`, make `report.json` aggregate only the active `ask()` run, and emit a visible `run_started` UI event with `run_id` and run directory. Strengthen the prompt so successful write tools are treated as completed actions.

**Tech Stack:** Python, pytest, existing `Mico`, `AgentLoop`, `ToolExecutor`, `RunStore`, and CLI renderer.

---

## Context

Observed run:

- Actual run directory: `E:\Java\面试\.mico\runs\152b86f37ad8`
- First `patch_file` succeeded with absolute path `E:\Java\面试\面试题.md`.
- Second `patch_file` retried the same replacement with relative path `面试题.md`.
- The second call failed with `validation_error: old_text not found in file` because the first call had already replaced the original text.
- `report.json` showed `tool_call_summary.ok = 8` even though the run had only four tool calls, because `build_report()` aggregates the full REPL history.
- User first looked at `10eeca803835`, which was a different run. REPL should expose the active run id and log location.

Current unrelated worktree item:

- `mico.egg-info/` is untracked and must not be staged, deleted, or modified for this task.

## Files

- Modify: `mico/tools.py`
  - Add `patch_file` idempotency when `old_text` is gone but `new_text` is already present exactly once.
- Modify: `mico/tool_executor.py`
  - Preserve structured metadata from idempotent `patch_file` results.
- Modify: `mico/runtime.py`
  - Add current-run history slicing to `build_report()`.
- Modify: `mico/agent_loop.py`
  - Save/report current run history start.
  - Emit `run_started` UI event with `run_id` and run directory.
- Modify: `mico/cli.py`
  - Render `run_started` and optionally `run_finished` with run id.
- Modify: `mico/prompt.py`
  - Tell the model not to repeat successful `patch_file`/`write_file` calls.
- Test: `tests/test_tools.py`
- Test: `tests/test_agent_loop.py`
- Test: `tests/test_cli_repl.py`
- Test: `tests/test_prompt.py`

## Task 1: Make Repeat Patch Idempotent

- [ ] **Step 1: Add failing tool-level test**

Add to `tests/test_tools.py`:

```python
def test_patch_file_already_applied_returns_metadata_ok(tmp_path):
    (tmp_path / "code.py").write_text("new\n", encoding="utf-8")
    workspace = Workspace.build(tmp_path)

    result = run_tool(workspace, "patch_file", {
        "path": "code.py",
        "old_text": "old",
        "new_text": "new",
    })

    parsed = json.loads(result)
    assert parsed["__tool_metadata__"]["ok"] is True
    assert parsed["__tool_metadata__"]["error_kind"] == "already_applied"
    assert parsed["__tool_metadata__"]["already_applied"] is True
    assert parsed["path"] == "code.py"
    assert (tmp_path / "code.py").read_text(encoding="utf-8") == "new\n"
```

Run:

```powershell
python -m pytest tests/test_tools.py::test_patch_file_already_applied_returns_metadata_ok -q
```

Expected before implementation: FAIL with `ValueError: old_text not found in file`.

- [ ] **Step 2: Add failing agent-level reproduction**

Add to `tests/test_agent_loop.py`:

```python
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
```

Run:

```powershell
python -m pytest tests/test_agent_loop.py::test_patch_file_same_change_absolute_then_relative_is_already_applied -q
```

Expected before implementation: FAIL because second call is `validation_error`.

- [ ] **Step 3: Implement idempotent result in `mico/tools.py`**

Update `_patch_file()` so the `count == 0` branch checks `new_text` before raising:

```python
def _patch_file(workspace, args):
    path = workspace.path(args["path"])
    old_text = str(args["old_text"])
    new_text = str(args["new_text"])
    content = path.read_text(encoding="utf-8")
    count = content.count(old_text)
    if count == 0:
        new_count = content.count(new_text)
        if new_count == 1:
            metadata = {
                "ok": True,
                "error_kind": "already_applied",
                "already_applied": True,
            }
            return json.dumps({
                "__tool_metadata__": metadata,
                "path": workspace.relative(path),
                "already_applied": True,
            }, ensure_ascii=False)
        if new_count > 1:
            raise ValueError("old_text not found and new_text found multiple times")
        raise ValueError("old_text not found in file")
    if count > 1:
        raise ValueError(f"old_text found {count} times, expected exactly 1")
    updated = content.replace(old_text, new_text, 1)
    path.write_text(updated, encoding="utf-8")
    return f"patched {workspace.relative(path)}"
```

Do not change the normal successful patch metadata; existing tests expect normal success to remain `error_kind="ok"` after `ToolExecutor` wraps plain text.

- [ ] **Step 4: Verify Task 1**

Run:

```powershell
python -m pytest tests/test_tools.py::test_patch_file_already_applied_returns_metadata_ok tests/test_agent_loop.py::test_patch_file_same_change_absolute_then_relative_is_already_applied -q
```

Expected after implementation: PASS.

## Task 2: Make Report Current-Run Scoped

- [ ] **Step 1: Add failing report test**

Add to `tests/test_agent_loop.py`:

```python
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
```

Run:

```powershell
python -m pytest tests/test_agent_loop.py::test_report_counts_only_current_repl_run_history -q
```

Expected before implementation: FAIL because the second report includes first run's successful patch.

- [ ] **Step 2: Store current run history start**

In `mico/runtime.py`, initialize a field:

```python
self._last_run_history_start = 0
```

In `mico/agent_loop.py`, immediately after recording the user message:

```python
agent.record({"role": "user", "content": user_message, "created_at": now()})
run_history_start = len(agent.history)
agent._last_run_history_start = run_history_start
```

All `agent.build_report(task_state, ...)` calls inside this run must pass `history_start=run_history_start`.

- [ ] **Step 3: Slice history in `build_report()`**

Change signature in `mico/runtime.py`:

```python
def build_report(self, task_state, verification_result=None, history_start=None):
    if history_start is None:
        history_start = self._last_run_history_start
    report_history = self.history[history_start:]
```

Then iterate over `report_history` instead of `self.history`, and set:

```python
"history_items": len(report_history),
```

Update the one-shot verification path in `mico/cli.py` to rely on the default `_last_run_history_start`, or explicitly pass:

```python
history_start=agent._last_run_history_start
```

- [ ] **Step 4: Verify Task 2**

Run:

```powershell
python -m pytest tests/test_agent_loop.py::test_report_counts_only_current_repl_run_history tests/test_agent_loop.py::test_report_includes_changed_files_for_successful_patch tests/test_agent_loop.py::test_report_tool_call_summary_counts_write_file_ok -q
```

Expected after implementation: PASS.

## Task 2.5: Do Not Count Already-Applied Patch As A New File Change

Codex review finding after initial implementation: `already_applied` should be a successful tool result so the agent can continue, but it is not a new write in the current run. `report.json` must not count `already_applied` as an applied patch or as a changed file unless another real write in the same run already added that file.

- [ ] **Step 1: Add failing report test**

Add to `tests/test_agent_loop.py`:

```python
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
```

Run:

```powershell
python -m pytest tests/test_agent_loop.py::test_report_does_not_count_already_applied_patch_as_new_change -q
```

Expected before implementation: FAIL because report counts the already-applied patch as a changed file and increments `patches_applied`.

- [ ] **Step 2: Adjust report aggregation**

In `mico/runtime.py`, only count `patch_file` as an applied patch when metadata says `error_kind == "ok"`:

```python
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
```

Do not change `tool_call_summary`: it should still count `already_applied` as its own successful non-mutating outcome.

- [ ] **Step 3: Verify Task 2.5**

Run:

```powershell
python -m pytest tests/test_agent_loop.py::test_report_does_not_count_already_applied_patch_as_new_change tests/test_agent_loop.py::test_patch_file_same_change_absolute_then_relative_is_already_applied tests/test_agent_loop.py::test_report_includes_changed_files_for_successful_patch -q
```

Expected after implementation: PASS.

## Task 3: Show Run ID and Log Path in REPL

- [ ] **Step 1: Add failing CLI renderer test**

Add to `tests/test_cli_repl.py`:

```python
def test_repl_output_shows_run_id_and_run_dir(monkeypatch, capsys):
    class RunIdAgent(ProgressAgent):
        def ask(self, message):
            self.ask_calls.append(message)
            cb = self.event_callback
            if cb:
                cb("run_started", {"run_id": "abc123", "run_dir": ".mico\\runs\\abc123"})
                cb("thinking", {})
                cb("run_finished", {"run_id": "abc123", "final_summary": "done"})
            return "done"

    agent = RunIdAgent()
    _patch_build_agent_with_progress(monkeypatch, agent)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", _make_input_side_effect(["hello", EOFError()]))

    main([])

    captured = capsys.readouterr()
    assert "abc123" in captured.out
    assert ".mico" in captured.out
    assert "runs" in captured.out
```

Run:

```powershell
python -m pytest tests/test_cli_repl.py::test_repl_output_shows_run_id_and_run_dir -q
```

Expected before implementation: FAIL because renderer ignores `run_started`.

- [ ] **Step 2: Emit `run_started` UI event**

In `mico/agent_loop.py`, after `agent.run_store.start_run(task_state)` and before first model request:

```python
agent.emit_ui_event("run_started", {
    "run_id": task_state.run_id,
    "run_dir": str(agent.run_store.run_dir(task_state)),
})
```

Keep existing trace event unchanged.

- [ ] **Step 3: Render run id in CLI**

In `mico/cli.py` `build_console_renderer()`:

```python
if etype == "run_started":
    print(f"mico: run {p.get('run_id', '?')} log={p.get('run_dir', '?')}")
elif etype == "thinking":
    ...
elif etype == "run_finished":
    run_id = p.get("run_id")
    if run_id:
        print(f"mico: done run={run_id}")
```

Do not print the final answer inside the renderer; `run_repl()` already prints it.

- [ ] **Step 4: Include run id in existing `run_finished` UI payloads**

In each `agent.emit_ui_event("run_finished", ...)` call in `mico/agent_loop.py`, include:

```python
{"run_id": task_state.run_id, "final_summary": clip(final, 120)}
```

For step-limit/model-error exits, also include the same `run_id`.

- [ ] **Step 5: Verify Task 3**

Run:

```powershell
python -m pytest tests/test_cli_repl.py::test_repl_output_shows_run_id_and_run_dir tests/test_cli_repl.py::test_repl_output_contains_progress_lines -q
```

Expected after implementation: PASS.

## Task 4: Prompt Guard Against Repeating Successful Writes

- [ ] **Step 1: Add failing prompt test**

Add to `tests/test_prompt.py`:

```python
def test_prompt_warns_not_to_repeat_successful_write_tools():
    builder = PromptBuilder()
    bundle = builder.build(
        tool_catalog=_sample_catalog(),
        approval_policy="auto",
        workspace_root="/tmp/ws",
        user_message="write file",
        history=[
            {"role": "tool", "name": "patch_file", "content": "patched code.py"},
        ],
    )

    assert "successful patch_file or write_file" in bundle.text
    assert "do not call the same write again" in bundle.text
```

Run:

```powershell
python -m pytest tests/test_prompt.py::test_prompt_warns_not_to_repeat_successful_write_tools -q
```

Expected before implementation: FAIL because current prompt only has XML-format reminder.

- [ ] **Step 2: Update prompt reminder**

In `mico/prompt.py`, change `_format_reminder()` to return a multi-line string:

```python
@staticmethod
def _format_reminder():
    return (
        "Reminder: respond with exactly one <tool> or <final> block. No prose outside the block.\n"
        "After a successful patch_file or write_file result, the file change is already applied; "
        "do not call the same write again. If you need confidence, use read_file to verify, then answer with <final>."
    )
```

- [ ] **Step 3: Verify Task 4**

Run:

```powershell
python -m pytest tests/test_prompt.py::test_prompt_warns_not_to_repeat_successful_write_tools tests/test_prompt.py -q
```

Expected after implementation: PASS.

## Full Verification

- [ ] Run focused tests:

```powershell
python -m pytest tests/test_tools.py tests/test_agent_loop.py tests/test_cli_repl.py tests/test_prompt.py -q
```

- [ ] Run full test suite:

```powershell
python -m pytest -q
```

- [ ] Run benchmarks:

```powershell
python -m benchmarks
```

- [ ] Run whitespace check:

```powershell
git diff --check
```

## Commit Guidance

Do not stage `mico.egg-info/`.

Recommended staged files:

```powershell
git add mico/tools.py mico/tool_executor.py mico/runtime.py mico/agent_loop.py mico/cli.py mico/prompt.py tests/test_tools.py tests/test_agent_loop.py tests/test_cli_repl.py tests/test_prompt.py docs/superpowers/plans/2026-06-25-mico-repeat-patch-report-observability.md
```

Recommended commit message:

```text
fix: improve repeat patch handling and run observability
```

## Self-Review Checklist

- [ ] Repeat patch with absolute then relative path no longer becomes `validation_error` when the replacement is already applied.
- [ ] Missing `old_text` without unique `new_text` still fails.
- [ ] `report.json` in REPL describes only the current `ask()` run.
- [ ] REPL output shows the active run id and log path.
- [ ] Prompt explicitly discourages repeating successful write tools.
- [ ] `mico.egg-info/` remains untouched and unstaged.
