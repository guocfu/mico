from mico.runtime import Mico
from mico.checkpoint import CHECKPOINT_SCHEMA_VERSION
from mico.state import TaskState


def test_parse_tool_json():
    kind, payload = Mico.parse('<tool>{"name":"list_files","args":{"path":"."}}</tool>')

    assert kind == "tool"
    assert payload["name"] == "list_files"


def test_parse_final():
    assert Mico.parse("<final>done</final>") == ("final", "done")


def test_parse_bad_tool_json_retries():
    kind, payload = Mico.parse("<tool>{bad</tool>")

    assert kind == "retry"
    assert "malformed tool JSON" in payload


# --- Task 2: Runtime checkpoint persistence ---


def _make_agent(tmp_path, session_store=None, session_id="test", resume_requested=False):
    """Create a minimal Mico agent for testing."""
    from mico.workspace import Workspace
    from mico.state import RunStore

    ws = Workspace.build(str(tmp_path))
    rs = RunStore(ws.root / ".mico" / "runs")
    return Mico(
        model_client=None,
        workspace=ws,
        run_store=rs,
        approval_policy="auto",
        max_steps=2,
        session_store=session_store,
        session_id=session_id,
        resume_requested=resume_requested,
    )


def test_task_state_has_checkpoint_fields():
    ts = TaskState.create("hello")
    assert ts.checkpoint_id == ""
    assert ts.resume_status == ""
    d = ts.to_dict()
    assert "checkpoint_id" in d
    assert "resume_status" in d


def test_completed_run_writes_checkpoint(tmp_path, monkeypatch):
    """A completed run should produce a checkpoint in the session."""
    from mico.memory_store import DurableMemory

    agent = _make_agent(tmp_path)

    # Fake model that returns final immediately
    class FakeModel:
        def complete(self, prompt):
            return "<final>all done</final>"

    agent.model_client = FakeModel()
    # Stub durable memory to avoid filesystem side effects
    agent.durable_memory = DurableMemory(tmp_path / ".mico" / "memory")

    agent.ask("test task")

    # Session should have a checkpoint
    assert agent.session["checkpoints"]["current_id"] is not None
    cp = agent.session["checkpoints"]["items"][agent.session["checkpoints"]["current_id"]]
    assert cp["schema_version"] == CHECKPOINT_SCHEMA_VERSION
    assert cp["trigger"] == "final"


def test_checkpoint_id_in_task_state(tmp_path):
    """After ask(), _last_task_state should have checkpoint_id set."""
    from mico.memory_store import DurableMemory

    agent = _make_agent(tmp_path)

    class FakeModel:
        def complete(self, prompt):
            return "<final>done</final>"

    agent.model_client = FakeModel()
    agent.durable_memory = DurableMemory(tmp_path / ".mico" / "memory")

    agent.ask("test task")

    assert agent._last_task_state.checkpoint_id != ""


def test_old_session_json_with_only_memory_loads(tmp_path):
    """Old session format with only 'memory' key should still load."""
    from mico.session_store import SessionStore

    ss = SessionStore(tmp_path / "sessions")
    # Save old-format session
    ss.save("old", {"session_id": "old", "memory": {"task_summary": "old task"}})

    agent = _make_agent(tmp_path, session_store=ss, session_id="old")
    assert agent.session_memory.task_summary == "old task"
    # Checkpoint shape should be initialized
    assert agent.session["checkpoints"]["current_id"] is None


def test_checkpoint_trigger_context_reduction(tmp_path):
    """When prompt metadata has sections_truncated, trigger should be context_reduction."""
    from mico.memory_store import DurableMemory
    from unittest.mock import patch

    agent = _make_agent(tmp_path)

    class FakeModel:
        def complete(self, prompt):
            return "<final>done</final>"

    agent.model_client = FakeModel()
    agent.durable_memory = DurableMemory(tmp_path / ".mico" / "memory")

    # Patch _create_post_run_checkpoint to inject truncation metadata before it reads
    original_create = agent._create_post_run_checkpoint

    def patched_create(user_message):
        agent._last_prompt_metadata = {"sections_truncated": ["history", "prefix"]}
        original_create(user_message)

    agent._create_post_run_checkpoint = patched_create

    agent.ask("test task")

    cp_id = agent.session["checkpoints"]["current_id"]
    cp = agent.session["checkpoints"]["items"][cp_id]
    assert cp["trigger"] == "context_reduction"


# --- Task 4: Runtime prompt resume injection ---


def test_resume_injects_checkpoint_into_prompt(tmp_path):
    """Explicit resume with valid checkpoint injects checkpoint text into prompt."""
    from mico.checkpoint import (
        CHECKPOINT_SCHEMA_VERSION,
        current_runtime_identity,
        create_checkpoint,
    )
    from mico.memory_store import DurableMemory

    # First run: create a checkpoint
    agent = _make_agent(tmp_path)

    class FakeModel:
        def complete(self, prompt):
            return "<final>done</final>"

    agent.model_client = FakeModel()
    agent.durable_memory = DurableMemory(tmp_path / ".mico" / "memory")
    agent.ask("build login page")

    # Second run: resume
    agent2 = _make_agent(tmp_path, session_id="test", resume_requested=True)
    agent2.model_client = FakeModel()
    agent2.durable_memory = DurableMemory(tmp_path / ".mico" / "memory")
    agent2.session_memory.set_task_summary("build login page")

    # Evaluate resume state
    from mico.checkpoint import evaluate_resume_state
    agent2.resume_state = evaluate_resume_state(agent2)

    # Build prompt and check checkpoint is injected
    bundle = agent2.build_prompt_bundle("continue")
    assert "Task checkpoint:" in bundle.text


def test_non_resume_does_not_inject_checkpoint(tmp_path):
    """Normal run (no resume) should not inject checkpoint text."""
    from mico.memory_store import DurableMemory

    agent = _make_agent(tmp_path)

    class FakeModel:
        def complete(self, prompt):
            return "<final>done</final>"

    agent.model_client = FakeModel()
    agent.durable_memory = DurableMemory(tmp_path / ".mico" / "memory")
    agent.ask("build login page")

    # Second run without resume
    agent2 = _make_agent(tmp_path, session_id="test")
    agent2.model_client = FakeModel()
    agent2.durable_memory = DurableMemory(tmp_path / ".mico" / "memory")

    bundle = agent2.build_prompt_bundle("continue")
    assert "Task checkpoint:" not in bundle.text


def test_stale_key_file_invalidates_summary(tmp_path):
    """Stale key file should invalidate its file summary and mark partial-stale."""
    from mico.checkpoint import CHECKPOINT_SCHEMA_VERSION, file_freshness
    from mico.memory_store import DurableMemory
    from mico.session_store import SessionStore

    # First run: create files and checkpoint
    ss = SessionStore(tmp_path / "sessions")
    agent = _make_agent(tmp_path, session_store=ss)

    class FakeModel:
        def complete(self, prompt):
            return "<final>done</final>"

    agent.model_client = FakeModel()
    agent.durable_memory = DurableMemory(tmp_path / ".mico" / "memory")

    # Create tracked file and a stable file (to keep workspace fingerprint stable)
    tracked = tmp_path / "src" / "main.py"
    tracked.parent.mkdir(parents=True, exist_ok=True)
    tracked.write_text("v1", encoding="utf-8")
    stable = tmp_path / "stable.txt"
    stable.write_text("unchanged", encoding="utf-8")

    agent.session_memory.remember_file("src/main.py")
    freshness = file_freshness(str(tracked), str(tmp_path))
    agent.session_memory.record_file_summary("src/main.py", "old code", freshness=freshness)
    agent.ask("task")

    # Change only the tracked file — but we need to restore workspace fingerprint
    # by making the checkpoint's fingerprint match the new state.
    # Instead: directly test evaluate_resume_state by matching fingerprints.
    tracked.write_text("v2", encoding="utf-8")

    # Resume
    agent2 = _make_agent(tmp_path, session_store=ss, session_id="test", resume_requested=True)
    agent2.model_client = FakeModel()
    agent2.durable_memory = DurableMemory(tmp_path / ".mico" / "memory")
    agent2.session_memory.set_task_summary("task")
    agent2.session_memory.record_file_summary("src/main.py", "old code", freshness=freshness)
    agent2.session_memory.remember_file("src/main.py")

    # Update the saved checkpoint's workspace fingerprint to match current state
    # so we isolate the partial-stale test from workspace-mismatch
    from mico.checkpoint import current_runtime_identity
    cp_id = agent2.session["checkpoints"]["current_id"]
    current_id = current_runtime_identity(agent2)
    agent2.session["checkpoints"]["items"][cp_id]["runtime_identity"]["workspace_fingerprint"] = current_id["workspace_fingerprint"]
    agent2.session["checkpoints"]["items"][cp_id]["runtime_identity"]["tool_signature"] = current_id["tool_signature"]

    from mico.checkpoint import evaluate_resume_state
    agent2.resume_state = evaluate_resume_state(agent2)
    assert agent2.resume_state["status"] == "partial-stale"
    assert "src/main.py" in agent2.resume_state["stale_paths"]
    # File summary should be invalidated
    assert "src/main.py" not in agent2.session_memory.file_summaries


def test_workspace_mismatch_in_prompt_metadata(tmp_path):
    """Workspace mismatch status should appear in prompt metadata."""
    from mico.checkpoint import CHECKPOINT_SCHEMA_VERSION
    from mico.memory_store import DurableMemory
    from mico.session_store import SessionStore

    ss = SessionStore(tmp_path / "sessions")
    agent = _make_agent(tmp_path, session_store=ss)

    class FakeModel:
        def complete(self, prompt):
            return "<final>done</final>"

    agent.model_client = FakeModel()
    agent.durable_memory = DurableMemory(tmp_path / ".mico" / "memory")
    agent.ask("task")

    # Tamper with the saved checkpoint's runtime identity
    cp_id = agent.session["checkpoints"]["current_id"]
    agent.session["checkpoints"]["items"][cp_id]["runtime_identity"]["approval_policy"] = "never"
    ss.save("test", agent.session)

    # Resume with different approval policy
    agent2 = _make_agent(tmp_path, session_store=ss, session_id="test", resume_requested=True)
    agent2.model_client = FakeModel()
    agent2.durable_memory = DurableMemory(tmp_path / ".mico" / "memory")
    agent2.approval_policy = "auto"

    from mico.checkpoint import evaluate_resume_state
    agent2.resume_state = evaluate_resume_state(agent2)

    bundle = agent2.build_prompt_bundle("continue")
    assert bundle.metadata["resume_status"] == "workspace-mismatch"
    assert len(bundle.metadata["runtime_identity_mismatch_fields"]) > 0


# --- Task 6: Report and trace safety ---


def test_report_contains_checkpoint_fields(tmp_path):
    """Report should include checkpoint_id and resume_status."""
    from mico.memory_store import DurableMemory

    agent = _make_agent(tmp_path)

    class FakeModel:
        def complete(self, prompt):
            return "<final>done</final>"

    agent.model_client = FakeModel()
    agent.durable_memory = DurableMemory(tmp_path / ".mico" / "memory")
    agent.ask("task")

    report = agent.build_report(agent._last_task_state)
    assert "checkpoint_id" in report
    assert report["checkpoint_id"] != ""
    assert "resume_status" in report
    assert "stale_paths" in report
    assert "runtime_identity_mismatch_fields" in report


def test_trace_has_checkpoint_created_event(tmp_path):
    """Trace should have a checkpoint_created event."""
    from mico.memory_store import DurableMemory

    agent = _make_agent(tmp_path)

    class FakeModel:
        def complete(self, prompt):
            return "<final>done</final>"

    agent.model_client = FakeModel()
    agent.durable_memory = DurableMemory(tmp_path / ".mico" / "memory")
    agent.ask("task")

    # Read trace file
    run_dir = agent.run_store.run_dir(agent._last_task_state)
    trace_path = run_dir / "trace.jsonl"
    assert trace_path.exists()
    events = []
    for line in trace_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            import json
            events.append(json.loads(line))

    cp_events = [e for e in events if e.get("event") == "checkpoint_created"]
    assert len(cp_events) == 1
    evt = cp_events[0]
    assert "checkpoint_id" in evt
    assert "trigger" in evt
    assert "key_file_count" in evt
    # Must NOT contain sensitive fields
    assert "current_goal" not in evt
    assert "summary" not in evt


def test_trace_checkpoint_event_no_full_body(tmp_path):
    """checkpoint_created trace event should not contain full checkpoint body."""
    from mico.memory_store import DurableMemory

    agent = _make_agent(tmp_path)

    class FakeModel:
        def complete(self, prompt):
            return "<final>done</final>"

    agent.model_client = FakeModel()
    agent.durable_memory = DurableMemory(tmp_path / ".mico" / "memory")
    agent.ask("task")

    run_dir = agent.run_store.run_dir(agent._last_task_state)
    trace_path = run_dir / "trace.jsonl"
    import json
    events = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    cp_events = [e for e in events if e.get("event") == "checkpoint_created"]
    assert len(cp_events) == 1
    evt = cp_events[0]
    # Should NOT have checkpoint body fields
    assert "task_state" not in evt
    assert "runtime_identity" not in evt
    assert "key_files" not in evt



def test_state_json_has_checkpoint_fields_after_ask(tmp_path):
    """Regression: state.json must contain checkpoint_id and resume_status after ask()."""
    import json
    from mico.memory_store import DurableMemory

    agent = _make_agent(tmp_path)

    class FakeModel:
        def complete(self, prompt):
            return "<final>done</final>"

    agent.model_client = FakeModel()
    agent.durable_memory = DurableMemory(tmp_path / ".mico" / "memory")
    agent.ask("test task")

    run_dir = agent.run_store.run_dir(agent._last_task_state)
    state_path = run_dir / "state.json"
    assert state_path.exists()
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state.get("checkpoint_id") != ""
    assert state.get("checkpoint_id") is not None
    assert "resume_status" in state
