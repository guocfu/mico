import json
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from mico.providers import FakeModelClient
from mico.runtime import Mico
from mico.state import RunStore
from mico.verification import run_verification
from mico.workspace import Workspace


class _FailingModelClient:
    def __init__(self, error_message="benchmark simulated model error"):
        self.error_message = error_message
        self.prompts = []

    def complete(self, prompt, *_args, **_kwargs):
        self.prompts.append(prompt)
        raise RuntimeError(self.error_message)


@dataclass
class CaseResult:
    name: str
    status: str
    run_id: str
    stop_reason: str
    failure_category: str
    assertions: dict
    group: str = "harness_regression"
    artifacts_complete: bool = False
    parser_retry_count: int = 0
    verification_ok: bool | None = None


@dataclass
class BenchmarkResult:
    total: int
    passed: int
    failed: int
    cases: list = field(default_factory=list)


_TASKS_PATH = Path(__file__).parent / "tasks.json"
_TEMP_ROOT = Path(__file__).resolve().parent.parent / ".tmp" / "benchmarks"


def load_tasks(path=None):
    path = Path(path) if path else _TASKS_PATH
    return json.loads(path.read_text(encoding="utf-8"))


def _run_case(task):
    _TEMP_ROOT.mkdir(parents=True, exist_ok=True)
    root = _TEMP_ROOT / f"case-{task['name']}-{uuid.uuid4().hex[:8]}"
    root.mkdir(parents=True, exist_ok=False)
    try:
        workspace = Workspace.build(root)
        runs_dir = root / ".mico" / "runs"

        for item in task.get("workspace_setup", []):
            file_path = root / item["path"]
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(item["content"], encoding="utf-8")

        if task.get("error_on_first"):
            model_client = _FailingModelClient()
        else:
            model_client = FakeModelClient(list(task["fake_outputs"]))

        agent = Mico(
            model_client=model_client,
            workspace=workspace,
            run_store=RunStore(runs_dir),
            approval_policy=task.get("approval_policy", "auto"),
            max_steps=task.get("max_steps", 4),
        )

        final_answer = agent.ask(task.get("user_message", task["name"]))

        verification_result = None
        verify_cmd = task.get("verify_cmd")
        if verify_cmd:
            verification_result = run_verification(root, verify_cmd)
            report = agent.build_report(agent._last_task_state, verification_result=verification_result)
            agent.run_store.write_report(agent._last_task_state, report)

        run_dirs = list(runs_dir.iterdir())
        assert len(run_dirs) == 1, f"expected 1 run dir, got {len(run_dirs)}"
        run_dir = run_dirs[0]

        artifact_paths = {
            "state.json": run_dir / "state.json",
            "trace.jsonl": run_dir / "trace.jsonl",
            "report.json": run_dir / "report.json",
        }
        artifacts_exist = {name: path.exists() for name, path in artifact_paths.items()}
        missing = [name for name, exists in artifacts_exist.items() if not exists]
        if missing:
            raise AssertionError(f"artifacts missing: {missing}")

        state_text = artifact_paths["state.json"].read_text(encoding="utf-8")
        trace_text = artifact_paths["trace.jsonl"].read_text(encoding="utf-8")
        report_text = artifact_paths["report.json"].read_text(encoding="utf-8")
        state = json.loads(state_text)
        report = json.loads(report_text)
        trace_events = [json.loads(line) for line in trace_text.splitlines() if line.strip()]
        parser_retry_count = sum(
            1
            for event in trace_events
            if event.get("event") == "model_parsed" and event.get("kind") == "retry"
        )

        file_contents = {}
        for relative_path in task.get("assertions", {}).get("file_contents", {}):
            file_path = root / relative_path
            file_contents[relative_path] = file_path.read_text(encoding="utf-8") if file_path.exists() else None

        return {
            "run_id": run_dir.name,
            "state": state,
            "report": report,
            "trace_events": trace_events,
            "history": list(agent.history),
            "artifacts_exist": artifacts_exist,
            "artifacts_complete": all(artifacts_exist.values()),
            "parser_retry_count": parser_retry_count,
            "verification_result": verification_result,
            "file_contents": file_contents,
            "final_answer": final_answer,
            "artifact_text": {
                "state.json": state_text,
                "trace.jsonl": trace_text,
                "report.json": report_text,
            },
        }
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _check_assertions(task, evidence):
    expected = task["assertions"]
    state = evidence["state"]
    report = evidence["report"]
    errors = []

    if expected.get("stop_reason") and state["stop_reason"] != expected["stop_reason"]:
        errors.append(f"stop_reason: expected {expected['stop_reason']!r}, got {state['stop_reason']!r}")

    if expected.get("failure_category") and report["failure_category"] != expected["failure_category"]:
        errors.append(
            f"failure_category: expected {expected['failure_category']!r}, got {report['failure_category']!r}"
        )

    if "tools_used" in expected:
        actual_tools = [tool for tool in state.get("tools", []) if tool]
        if actual_tools != expected["tools_used"]:
            errors.append(f"tools_used: expected {expected['tools_used']}, got {actual_tools}")

    if expected.get("artifacts_exist", True):
        missing = [name for name, exists in evidence["artifacts_exist"].items() if not exists]
        if missing:
            errors.append(f"artifacts missing: {missing}")

    if "tool_call_summary" in expected:
        actual_summary = report.get("tool_call_summary", {})
        for error_kind, expected_count in expected["tool_call_summary"].items():
            actual_count = actual_summary.get(error_kind, 0)
            if actual_count != expected_count:
                errors.append(
                    f"tool_call_summary[{error_kind}]: expected {expected_count}, got {actual_count}"
                )

    if "history_contains" in expected:
        history_text = json.dumps(evidence["history"], ensure_ascii=False)
        for snippet in expected["history_contains"]:
            if snippet not in history_text:
                errors.append(f"history missing snippet: {snippet!r}")

    if "file_contents" in expected:
        for relative_path, expected_content in expected["file_contents"].items():
            actual_content = evidence["file_contents"].get(relative_path)
            if actual_content != expected_content:
                errors.append(
                    f"file_contents[{relative_path}]: expected {expected_content!r}, got {actual_content!r}"
                )

    if "trace_retry_error_kinds" in expected:
        actual_error_kinds = [
            event.get("error_kind")
            for event in evidence["trace_events"]
            if event.get("event") == "model_parsed" and event.get("kind") == "retry"
        ]
        if actual_error_kinds != expected["trace_retry_error_kinds"]:
            errors.append(
                f"trace_retry_error_kinds: expected {expected['trace_retry_error_kinds']}, got {actual_error_kinds}"
            )

    if "report_absent_keys" in expected:
        for key in expected["report_absent_keys"]:
            if key in report:
                errors.append(f"report should not contain key: {key}")

    if expected.get("raw_model_outputs_absent_from_report"):
        report_text = evidence["artifact_text"]["report.json"]
        for raw in task.get("fake_outputs", []):
            if raw and raw in report_text:
                errors.append(f"report contains raw model output for task {task['name']}")

    if "changed_files" in expected:
        actual_changed = report.get("changed_files", [])
        if actual_changed != expected["changed_files"]:
            errors.append(
                f"changed_files: expected {expected['changed_files']}, got {actual_changed}"
            )

    if "verification_ok" in expected:
        actual = report.get("verification_ok")
        if actual != expected["verification_ok"]:
            errors.append(f"verification_ok: expected {expected['verification_ok']}, got {actual}")

    if "verification_exit_code" in expected:
        actual = report.get("verification_exit_code")
        if actual != expected["verification_exit_code"]:
            errors.append(f"verification_exit_code: expected {expected['verification_exit_code']}, got {actual}")

    if "verification_timed_out" in expected:
        actual = report.get("verification_timed_out")
        if actual != expected["verification_timed_out"]:
            errors.append(f"verification_timed_out: expected {expected['verification_timed_out']}, got {actual}")

    if "files_written" in expected:
        actual_written = report.get("files_written", [])
        if actual_written != expected["files_written"]:
            errors.append(
                f"files_written: expected {expected['files_written']}, got {actual_written}"
            )

    if "commands_run_count" in expected:
        actual_commands = report.get("commands_run", [])
        if len(actual_commands) != expected["commands_run_count"]:
            errors.append(
                f"commands_run_count: expected {expected['commands_run_count']}, got {len(actual_commands)}"
            )

    if "commands_run_present" in expected:
        actual_commands = report.get("commands_run", [])
        for key in expected["commands_run_present"]:
            if not any(key in cmd for cmd in actual_commands):
                errors.append(f"commands_run missing key in any entry: {key}")

    if "verification_summary_present" in expected:
        if expected["verification_summary_present"] and "verification_summary" not in report:
            errors.append("verification_summary missing from report")
        elif not expected["verification_summary_present"] and "verification_summary" in report:
            errors.append("verification_summary should not be in report")

    return errors


def run_benchmark(tasks=None):
    if tasks is None:
        tasks = load_tasks()

    result = BenchmarkResult(total=len(tasks), passed=0, failed=0)

    for task in tasks:
        name = task["name"]
        group = task.get("group", "harness_regression")
        try:
            evidence = _run_case(task)
            state = evidence["state"]
            report = evidence["report"]
            errors = _check_assertions(task, evidence)
            if errors:
                status = "FAIL"
                result.failed += 1
            else:
                status = "PASS"
                result.passed += 1
            result.cases.append(
                CaseResult(
                    name=name,
                    status=status,
                    run_id=evidence["run_id"],
                    stop_reason=state.get("stop_reason", ""),
                    failure_category=report.get("failure_category", ""),
                    assertions={"errors": errors},
                    group=group,
                    artifacts_complete=evidence["artifacts_complete"],
                    parser_retry_count=evidence["parser_retry_count"],
                    verification_ok=evidence["verification_result"].ok if evidence.get("verification_result") else None,
                )
            )
        except Exception as exc:
            result.failed += 1
            result.cases.append(
                CaseResult(
                    name=name,
                    status="ERROR",
                    run_id="",
                    stop_reason="",
                    failure_category="",
                    assertions={"errors": [str(exc)]},
                    group=group,
                    artifacts_complete=False,
                    parser_retry_count=0,
                    verification_ok=None,
                )
            )

    return result


def result_to_dict(result):
    from .metrics import compute_metrics

    return {
        "total": result.total,
        "passed": result.passed,
        "failed": result.failed,
        "metrics": compute_metrics(result),
        "cases": [
            {
                "name": case.name,
                "group": case.group,
                "status": case.status,
                "run_id": case.run_id,
                "stop_reason": case.stop_reason,
                "failure_category": case.failure_category,
                "artifacts_complete": case.artifacts_complete,
                "parser_retry_count": case.parser_retry_count,
                "verification_ok": case.verification_ok,
                "assertions": case.assertions,
            }
            for case in result.cases
        ],
    }


def write_results(result, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(result_to_dict(result), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def write_markdown_summary(result, path):
    from .metrics import markdown_summary

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown_summary(result), encoding="utf-8")
    return path


def print_summary(result):
    for case in result.cases:
        marker = "PASS" if case.status == "PASS" else "FAIL"
        print(f"  [{marker}] {case.name}")
        if case.assertions.get("errors"):
            for err in case.assertions["errors"]:
                print(f"         {err}")
    print(f"\n{result.passed}/{result.total} passed, {result.failed} failed")
