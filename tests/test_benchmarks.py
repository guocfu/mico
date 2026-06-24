import json

from benchmarks.runner import (
    BenchmarkResult,
    CaseResult,
    load_tasks,
    result_to_dict,
    run_benchmark,
    write_markdown_summary,
    write_results,
    _check_assertions,
)
from benchmarks.metrics import compute_metrics, markdown_summary


def test_load_tasks_returns_all_cases():
    tasks = load_tasks()

    assert len(tasks) == 17
    names = [t["name"] for t in tasks]
    assert "list_files_success" in names
    assert "read_file_success" in names
    assert "search_success" in names
    assert "patch_file_success" in names
    assert "patch_file_denied" in names
    assert "path_escape_rejected" in names
    assert "malformed_retry_then_success" in names
    assert "model_error_artifacts" in names
    assert "unknown_tool_rejected" in names
    assert "repeated_call_rejected" in names
    assert "patch_and_verify_success" in names
    assert "verify_fail_after_bad_patch" in names
    assert "write_file_success" in names
    assert "write_file_denied" in names
    assert "run_command_success" in names
    assert "run_command_denied" in names
    assert "run_command_failure_output" in names
    assert all("group" in t for t in tasks)


def test_run_benchmark_all_cases_pass():
    result = run_benchmark()

    assert result.total == 17
    assert result.failed == 0, (
        f"Failed cases: {[c.name for c in result.cases if c.status != 'PASS']}"
    )
    assert result.passed == 17


def test_result_json_has_correct_structure():
    result = run_benchmark()
    data = result_to_dict(result)

    assert "total" in data
    assert "passed" in data
    assert "failed" in data
    assert "metrics" in data
    assert "cases" in data
    assert len(data["cases"]) == 17

    for case in data["cases"]:
        assert "name" in case
        assert "group" in case
        assert "status" in case
        assert "run_id" in case
        assert "stop_reason" in case
        assert "failure_category" in case
        assert "artifacts_complete" in case
        assert "parser_retry_count" in case
        assert "verification_ok" in case
        assert "assertions" in case
    text = json.dumps(data)
    assert "<tool>" not in text
    assert "<final>" not in text
    assert "not xml at all" not in text


def test_each_case_has_nonempty_run_id():
    result = run_benchmark()

    for case in result.cases:
        assert case.run_id, f"{case.name}: run_id should not be empty"


def test_model_error_case_has_correct_fields():
    result = run_benchmark()
    case = next(c for c in result.cases if c.name == "model_error_artifacts")

    assert case.status == "PASS"
    assert case.stop_reason == "model_error"
    assert case.failure_category == "model_error"


def test_patch_file_denied_case_has_correct_fields():
    result = run_benchmark()
    case = next(c for c in result.cases if c.name == "patch_file_denied")

    assert case.status == "PASS"
    assert case.stop_reason == "final"
    assert case.failure_category == "success"


def test_tool_governance_group_cases_pass():
    tasks = [task for task in load_tasks() if task["group"] == "tool_governance"]
    result = run_benchmark(tasks)

    assert result.total == 6
    assert result.failed == 0
    assert all(case.group == "tool_governance" for case in result.cases)


def test_unknown_tool_case_has_correct_fields():
    result = run_benchmark()
    case = next(c for c in result.cases if c.name == "unknown_tool_rejected")

    assert case.status == "PASS"
    assert case.stop_reason == "final"
    assert case.failure_category == "success"
    assert case.group == "tool_governance"


def test_repeated_call_case_has_correct_fields():
    result = run_benchmark()
    case = next(c for c in result.cases if c.name == "repeated_call_rejected")

    assert case.status == "PASS"
    assert case.stop_reason == "final"
    assert case.failure_category == "success"
    assert case.group == "tool_governance"


def test_malformed_retry_case_records_parser_retry_count():
    result = run_benchmark()
    case = next(c for c in result.cases if c.name == "malformed_retry_then_success")

    assert case.parser_retry_count == 1


def test_compute_metrics_from_benchmark_result():
    result = run_benchmark()
    metrics = compute_metrics(result)

    assert metrics["total"] == 17
    assert metrics["passed"] == 17
    assert metrics["failed"] == 0
    assert metrics["pass_rate"] == 1.0
    assert metrics["artifact_completeness_rate"] == 1.0
    assert metrics["failure_attribution_coverage"] == 1.0
    assert metrics["tool_guard_pass_rate"] == 1.0
    assert metrics["tool_governance_total"] == 6
    assert metrics["parser_retry_count_total"] == 1
    assert metrics["verifier_pass_rate"] == 0.5
    assert metrics["verification_total"] == 2


def test_markdown_summary_contains_metrics_table():
    result = run_benchmark()
    text = markdown_summary(result)

    assert "# Mico Benchmark Summary" in text
    assert "| Pass rate | 100.00% |" in text
    assert "| Tool guard pass rate | 100.00% |" in text
    assert "malformed_retry_then_success" in text


def test_check_assertions_detects_wrong_stop_reason():
    evidence = _evidence(
        state={"stop_reason": "step_limit", "tools": []},
        report={"failure_category": "step_limit"},
    )
    task = {"assertions": {"stop_reason": "final", "failure_category": "success"}}

    errors = _check_assertions(task, evidence)

    assert len(errors) == 2
    assert "stop_reason" in errors[0]
    assert "failure_category" in errors[1]


def test_check_assertions_detects_wrong_failure_category():
    evidence = _evidence(
        state={"stop_reason": "final", "tools": []},
        report={"failure_category": "model_error"},
    )
    task = {"assertions": {"stop_reason": "final", "failure_category": "success"}}

    errors = _check_assertions(task, evidence)

    assert len(errors) == 1
    assert "failure_category" in errors[0]


def test_check_assertions_detects_wrong_tools():
    evidence = _evidence(
        state={"stop_reason": "final", "tools": ["read_file"]},
        report={"failure_category": "success"},
    )
    task = {"assertions": {"stop_reason": "final", "failure_category": "success", "tools_used": ["list_files"]}}

    errors = _check_assertions(task, evidence)

    assert len(errors) == 1
    assert "tools_used" in errors[0]


def test_failure_summary_aggregation():
    result = BenchmarkResult(total=3, passed=1, failed=2)
    result.cases = [
        CaseResult("good", "PASS", "abc", "final", "success", {"errors": []}),
        CaseResult("bad1", "FAIL", "def", "step_limit", "step_limit", {"errors": ["wrong stop_reason"]}),
        CaseResult("bad2", "ERROR", "", "", "", {"errors": ["exception"]}),
    ]

    failed_cases = [c for c in result.cases if c.status != "PASS"]

    assert len(failed_cases) == 2
    assert failed_cases[0].name == "bad1"
    assert failed_cases[1].name == "bad2"


def test_load_tasks_from_custom_path(tmp_path):
    custom_tasks = [
        {
            "name": "simple",
            "description": "simple test",
            "fake_outputs": ["<final>ok</final>"],
            "workspace_setup": [],
            "assertions": {"stop_reason": "final", "failure_category": "success"},
        }
    ]
    path = tmp_path / "custom_tasks.json"
    path.write_text(json.dumps(custom_tasks), encoding="utf-8")

    tasks = load_tasks(path)

    assert len(tasks) == 1
    assert tasks[0]["name"] == "simple"


def test_result_to_dict_json_serializable():
    result = run_benchmark()
    data = result_to_dict(result)

    serialized = json.dumps(data)
    assert isinstance(serialized, str)
    assert len(serialized) > 0


def test_write_results_creates_metrics_json(tmp_path):
    result = run_benchmark()
    output = write_results(result, tmp_path / "results" / "latest.json")

    assert output.exists()
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["total"] == 17
    assert data["failed"] == 0
    assert data["metrics"]["pass_rate"] == 1.0
    text = json.dumps(data)
    assert "<tool>" not in text
    assert "<final>" not in text
    assert "not xml at all" not in text


def test_write_markdown_summary_creates_file(tmp_path):
    result = run_benchmark()
    output = write_markdown_summary(result, tmp_path / "results" / "latest.md")

    assert output.exists()
    text = output.read_text(encoding="utf-8")
    assert "Mico Benchmark Summary" in text
    assert "Parser retry count" in text


def test_verification_group_cases_pass():
    tasks = [task for task in load_tasks() if task["group"] == "verification"]
    result = run_benchmark(tasks)

    assert result.total == 2
    assert result.failed == 0
    assert all(case.group == "verification" for case in result.cases)


def test_patch_and_verify_success_case():
    result = run_benchmark()
    case = next(c for c in result.cases if c.name == "patch_and_verify_success")

    assert case.status == "PASS"
    assert case.stop_reason == "final"
    assert case.failure_category == "success"
    assert case.verification_ok is True


def test_verify_fail_after_bad_patch_case():
    result = run_benchmark()
    case = next(c for c in result.cases if c.name == "verify_fail_after_bad_patch")

    assert case.status == "PASS"
    assert case.stop_reason == "final"
    assert case.failure_category == "success"
    assert case.verification_ok is False


def test_markdown_summary_contains_verifier_pass_rate():
    result = run_benchmark()
    text = markdown_summary(result)

    assert "Verifier pass rate" in text


def test_benchmark_detects_failed_case():
    tasks = [
        {
            "name": "intentional_failure",
            "fake_outputs": ["<final>ok</final>"],
            "workspace_setup": [],
            "assertions": {"stop_reason": "step_limit", "failure_category": "success"},
        }
    ]

    result = run_benchmark(tasks)

    assert result.total == 1
    assert result.passed == 0
    assert result.failed == 1
    assert result.cases[0].status == "FAIL"
    assert "stop_reason" in result.cases[0].assertions["errors"][0]


def _evidence(state, report):
    return {
        "state": state,
        "report": report,
        "trace_events": [],
        "history": [],
        "artifacts_exist": {"state.json": True, "trace.jsonl": True, "report.json": True},
        "file_contents": {},
        "final_answer": "",
        "artifact_text": {"state.json": "", "trace.jsonl": "", "report.json": ""},
    }
