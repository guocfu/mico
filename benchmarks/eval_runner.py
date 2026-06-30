import json
import shutil
import uuid
from pathlib import Path

from mico.checkpoint import (
    CHECKPOINT_FULL_VALID_STATUS,
    CHECKPOINT_NONE_STATUS,
    evaluate_resume_state,
)
from mico.context_manager import ContextManager
from mico.memory import SessionMemoryState
from mico.prompt import PromptBuilder
from mico.providers import FakeModelClient
from mico.runtime import Mico
from mico.session_store import SessionStore
from mico.state import RunStore
from mico.workspace import Workspace

from .eval_config import BASELINE, CURRENT
from .eval_metrics import compute_eval_metrics, markdown_eval_summary


_EVAL_TASKS_PATH = Path(__file__).parent / "eval_tasks.json"
_TEMP_ROOT = Path(__file__).resolve().parent.parent / ".tmp" / "eval_benchmarks"


class PromptAwareFakeModel:
    """Fake model that asks for read_file only when the prompt lacks a known fact."""

    def __init__(self, summary_token, file_path, on_miss_tool=True):
        self.summary_token = summary_token
        self.file_path = file_path
        self.on_miss_tool = on_miss_tool
        self.prompts = []
        self._returned_first_tool = False

    def complete(self, prompt, *_args, **_kwargs):
        self.prompts.append(prompt)
        if self.summary_token in prompt:
            return "<final>I can answer from memory.</final>"
        if self.on_miss_tool and not self._returned_first_tool:
            self._returned_first_tool = True
            return (
                '<tool>{"name":"read_file","args":{"path":"'
                + self.file_path
                + '"}}</tool>'
            )
        return "<final>I had to read the file.</final>"


def load_eval_tasks(path=None):
    path = Path(path) if path else _EVAL_TASKS_PATH
    return json.loads(path.read_text(encoding="utf-8"))


def run_eval(tasks=None, *, baseline_config=BASELINE, current_config=CURRENT):
    if tasks is None:
        tasks = load_eval_tasks()
    cases = []
    for task in tasks:
        group = task.get("group", "")
        try:
            if group == "context_compression":
                case = _make_context_compression_case(
                    task,
                    baseline_config=baseline_config,
                    current_config=current_config,
                )
            elif group == "memory_reuse":
                case = _make_memory_reuse_case(
                    task,
                    baseline_config=baseline_config,
                    current_config=current_config,
                )
            elif group == "checkpoint_resume":
                case = _make_checkpoint_resume_case(
                    task,
                    baseline_config=baseline_config,
                    current_config=current_config,
                )
            else:
                case = _failure_case(task, "unknown group: " + group)
        except Exception as exc:
            case = _failure_case(task, type(exc).__name__ + ": " + str(exc))
        cases.append(case)
    return {"cases": cases}


def result_to_dict(result):
    cases = result.get("cases", [])
    total = len(cases)
    passed = sum(1 for case in cases if case.get("status") == "PASS")
    failed = total - passed
    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "cases": cases,
        "metrics": compute_eval_metrics(result),
    }


def write_eval_results(result, json_path, markdown_path):
    data = result_to_dict(result)
    json_path = Path(json_path)
    markdown_path = Path(markdown_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(markdown_eval_summary(data), encoding="utf-8")
    return json_path, markdown_path


def _failure_case(task, error):
    return {
        "name": task.get("name", "(unnamed)"),
        "group": task.get("group", ""),
        "status": "FAIL",
        "baseline": {},
        "current": {},
        "expected_resume_status": task.get("expected_resume_status"),
        "errors": [error],
    }


def _build_prompt_metadata(session_memory, user_message, history, checkpoint_text, config):
    prompt_builder = PromptBuilder()
    if config.context_compression:
        total_budget = config.total_budget
        section_budgets = None
    else:
        total_budget = config.unbounded_total_budget
        section_budgets = config.unbounded_section_budgets
    ctx = ContextManager(
        prompt_builder,
        total_budget=total_budget,
        section_budgets=section_budgets,
    )
    bundle = ctx.build(
        tool_catalog=_tool_catalog(),
        approval_policy="auto",
        workspace_root=".",
        user_message=user_message,
        history=history,
        session_memory=session_memory,
        checkpoint_text=checkpoint_text,
    )
    return bundle.metadata


def _make_context_compression_case(task, *, baseline_config, current_config):
    user_message = task.get("user_message", "test")
    history = _synthetic_history(task)
    session_memory = _synthetic_session_memory(task)
    checkpoint_text = _synthetic_checkpoint_text(task)

    baseline_meta = _build_prompt_metadata(
        session_memory,
        user_message,
        history,
        checkpoint_text,
        baseline_config,
    )
    current_meta = _build_prompt_metadata(
        session_memory,
        user_message,
        history,
        checkpoint_text,
        current_config,
    )
    current_request_preserved = current_meta.get("current_request_preserved_rate", 0.0)
    compression_rate = _compression_rate(
        baseline_meta["prompt_chars"],
        current_meta["prompt_chars"],
    )
    ok = (
        baseline_meta["prompt_chars"] >= current_meta["prompt_chars"]
        and current_request_preserved == 1.0
    )
    return {
        "name": task["name"],
        "group": task["group"],
        "status": "PASS" if ok else "FAIL",
        "baseline": {
            "prompt_chars": baseline_meta["prompt_chars"],
            "context_compression": baseline_config.context_compression,
        },
        "current": {
            "prompt_chars": current_meta["prompt_chars"],
            "context_compression": current_config.context_compression,
            "current_request_preserved_rate": current_request_preserved,
            "sections_truncated": current_meta.get("sections_truncated", []),
            "older_read_file_entries_used": current_meta.get("older_read_file_entries_used", 0),
        },
        "compression_rate": compression_rate,
        "expected_resume_status": task.get("expected_resume_status"),
        "errors": [] if ok else ["current prompt is larger than baseline or request was clipped"],
    }


def _make_memory_reuse_case(task, *, baseline_config, current_config):
    baseline = _run_memory_followup(task, baseline_config)
    current = _run_memory_followup(task, current_config)
    ok = (
        baseline["followup_read_file_count"] > current["followup_read_file_count"]
        and current["used_memory_summary"] is True
    )
    return {
        "name": task["name"],
        "group": task["group"],
        "status": "PASS" if ok else "FAIL",
        "baseline": baseline,
        "current": current,
        "expected_resume_status": task.get("expected_resume_status"),
        "errors": [] if ok else ["memory-enabled run did not reduce follow-up reads"],
    }


def _make_checkpoint_resume_case(task, *, baseline_config, current_config):
    baseline = _run_checkpoint_resume(task, baseline_config)
    current = _run_checkpoint_resume(task, current_config)
    expected = task.get("expected_resume_status", CHECKPOINT_FULL_VALID_STATUS)
    ok = (
        baseline["resume_status"] == CHECKPOINT_NONE_STATUS
        and current["resume_status"] == expected
        and current["trusted_stale_summary"] is False
    )
    return {
        "name": task["name"],
        "group": task["group"],
        "status": "PASS" if ok else "FAIL",
        "baseline": baseline,
        "current": current,
        "expected_resume_status": expected,
        "errors": [] if ok else ["expected " + expected + " got " + current["resume_status"]],
    }


def _run_memory_followup(task, config):
    _TEMP_ROOT.mkdir(parents=True, exist_ok=True)
    root = _TEMP_ROOT / ("memory-" + task["name"] + "-" + uuid.uuid4().hex[:8])
    root.mkdir(parents=True, exist_ok=False)
    try:
        workspace = Workspace.build(root)
        runs_dir = root / ".mico" / "runs"
        sessions_dir = root / ".mico" / "sessions"
        file_path = root / task["path"]
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(task["content"], encoding="utf-8")

        if config.memory:
            seed_model = FakeModelClient([
                _read_file_tool(task["path"]),
                "<final>seeded memory</final>",
            ])
            seed_agent = Mico(
                model_client=seed_model,
                workspace=workspace,
                run_store=RunStore(runs_dir),
                session_store=SessionStore(sessions_dir),
                approval_policy="auto",
                max_steps=4,
                session_id="eval_memory",
            )
            seed_agent.ask("read " + task["path"])
            session_id = "eval_memory"
        else:
            session_id = "eval_memory_baseline"

        followup_model = PromptAwareFakeModel(task["summary_token"], task["path"])
        followup_agent = Mico(
            model_client=followup_model,
            workspace=workspace,
            run_store=RunStore(runs_dir),
            session_store=SessionStore(sessions_dir),
            approval_policy="auto",
            max_steps=4,
            session_id=session_id,
        )
        followup_agent.ask("what is in " + task["path"] + "?")
        followup_read_count = _count_read_file_calls(followup_agent.history)
        used_memory_summary = any(task["summary_token"] in prompt for prompt in followup_model.prompts)

        return {
            "memory": config.memory,
            "followup_read_file_count": followup_read_count,
            "used_memory_summary": used_memory_summary,
        }
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _run_checkpoint_resume(task, config):
    if not config.checkpoint:
        return {
            "checkpoint": False,
            "resume_status": CHECKPOINT_NONE_STATUS,
            "drift_detected": False,
            "trusted_stale_summary": False,
            "stale_paths": [],
            "runtime_identity_mismatch_fields": [],
        }

    _TEMP_ROOT.mkdir(parents=True, exist_ok=True)
    root = _TEMP_ROOT / ("resume-" + task["name"] + "-" + uuid.uuid4().hex[:8])
    root.mkdir(parents=True, exist_ok=False)
    try:
        workspace = Workspace.build(root)
        runs_dir = root / ".mico" / "runs"
        sessions_dir = root / ".mico" / "sessions"
        file_path = root / "key_file.py"
        file_path.write_text("x = 1\n", encoding="utf-8")

        model = FakeModelClient([
            _read_file_tool("key_file.py"),
            "<final>checkpoint seed complete</final>",
        ])
        agent = Mico(
            model_client=model,
            workspace=workspace,
            run_store=RunStore(runs_dir),
            session_store=SessionStore(sessions_dir),
            approval_policy="auto",
            max_steps=4,
            session_id="eval_resume",
        )
        agent.ask("read key_file.py")
        agent._save_session()

        mutation = task.get("mutation")
        if mutation == "change_key_file":
            file_path.write_text("x = 2\nchanged\n", encoding="utf-8")
        elif mutation == "schema_version":
            _mutate_checkpoint_schema(sessions_dir / "eval_resume.json")

        resume_policy = "ask" if mutation == "approval_policy" else "auto"
        resume_agent = Mico(
            model_client=FakeModelClient(["<final>resumed</final>"]),
            workspace=workspace,
            run_store=RunStore(runs_dir),
            session_store=SessionStore(sessions_dir),
            approval_policy=resume_policy,
            max_steps=4,
            session_id="eval_resume",
            resume_requested=True,
        )

        resume_result = evaluate_resume_state(resume_agent)
        actual_status = resume_result["status"]
        stale_paths = resume_result.get("stale_paths", [])
        trusted_stale = bool(stale_paths) and actual_status != "partial-stale"
        return {
            "checkpoint": True,
            "resume_status": actual_status,
            "drift_detected": actual_status != CHECKPOINT_FULL_VALID_STATUS,
            "trusted_stale_summary": trusted_stale,
            "stale_paths": stale_paths,
            "runtime_identity_mismatch_fields": resume_result.get(
                "runtime_identity_mismatch_fields", []
            ),
        }
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _synthetic_history(task):
    history_items = int(task.get("history_items", 10))
    history_payload_chars = int(task.get("history_payload_chars", 160))
    read_file_ranges = int(task.get("read_file_ranges", 0))
    read_result_chars = int(task.get("read_result_chars", 420))

    history = []
    for i in range(history_items):
        history.append({
            "role": "user",
            "content": "message " + str(i) + " " + ("x" * history_payload_chars),
        })
        history.append({
            "role": "assistant",
            "content": "reply " + str(i) + " " + ("y" * (history_payload_chars // 2)),
        })

    for i in range(read_file_ranges):
        start = i * 40 + 1
        end = start + 39
        history.append({
            "role": "tool",
            "name": "read_file",
            "args": {"path": "src/large.py", "start": start, "end": end},
            "content": "range " + str(i) + " " + ("z" * read_result_chars),
            "metadata": {"ok": True, "error_kind": "ok"},
        })
    return history


def _synthetic_session_memory(task):
    memory = SessionMemoryState()
    memory_notes = int(task.get("memory_notes", 0))
    file_summaries = int(task.get("file_summaries", 0))
    for i in range(memory_notes):
        memory.append_episodic_note(
            "note " + str(i) + " " + ("m" * int(task.get("memory_note_chars", 160))),
            tags=["eval", "note" + str(i)],
        )
    for i in range(file_summaries):
        path = "src/file_" + str(i) + ".py"
        memory.remember_file(path)
        memory.record_file_summary(
            path,
            "summary " + str(i) + " " + ("s" * int(task.get("file_summary_chars", 160))),
            freshness="eval-" + str(i),
        )
    return memory


def _synthetic_checkpoint_text(task):
    checkpoint_chars = int(task.get("checkpoint_chars", 0))
    if checkpoint_chars <= 0:
        return ""
    return "Task checkpoint:\n  summary: " + ("c" * checkpoint_chars)


def _mutate_checkpoint_schema(session_path):
    if not session_path.exists():
        return
    data = json.loads(session_path.read_text(encoding="utf-8"))
    checkpoints = data.get("checkpoints", {})
    current_id = checkpoints.get("current_id")
    items = checkpoints.get("items", {})
    if current_id in items:
        items[current_id]["schema_version"] = "checkpoint-v999"
    session_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _count_read_file_calls(history):
    return sum(
        1
        for item in history
        if item.get("role") == "tool" and item.get("name") == "read_file"
    )


def _read_file_tool(path):
    return '<tool>{"name":"read_file","args":{"path":"' + path + '"}}</tool>'


def _compression_rate(baseline_chars, current_chars):
    if baseline_chars <= 0:
        return 0.0
    return round((baseline_chars - current_chars) / baseline_chars, 4)


def _tool_catalog():
    return [
        {
            "name": "list_files",
            "description": "List files in the workspace.",
            "schema": '{"path": "str=."}',
            "allowed": True,
            "requires_approval": False,
            "read_only": True,
            "concurrency_safe": True,
            "max_result_chars": 4000,
        },
        {
            "name": "read_file",
            "description": "Read a UTF-8 file by line range.",
            "schema": '{"path": "str", "start": "int=1", "end": "int=80"}',
            "allowed": True,
            "requires_approval": False,
            "read_only": True,
            "concurrency_safe": True,
            "max_result_chars": 4000,
        },
        {
            "name": "search",
            "description": "Search text in the workspace.",
            "schema": '{"pattern": "str", "path": "str=."}',
            "allowed": True,
            "requires_approval": False,
            "read_only": True,
            "concurrency_safe": True,
            "max_result_chars": 4000,
        },
    ]
