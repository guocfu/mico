from benchmarks.eval_config import BASELINE, CURRENT, AblationConfig
from benchmarks.eval_metrics import compute_eval_metrics
from benchmarks.eval_runner import load_eval_tasks, run_eval, result_to_dict
from benchmarks.eval_metrics import markdown_eval_summary
import json


def test_ablation_configs_define_baseline_and_current():
    assert BASELINE.memory is False
    assert BASELINE.context_compression is False
    assert BASELINE.checkpoint is False
    assert CURRENT.memory is True
    assert CURRENT.context_compression is True
    assert CURRENT.checkpoint is True
    assert BASELINE.total_budget == CURRENT.total_budget
    assert BASELINE.unbounded_total_budget > CURRENT.total_budget


def test_compute_eval_metrics_context_compression():
    result = {
        "cases": [
            {
                "group": "context_compression",
                "baseline": {"prompt_chars": 1000},
                "current": {
                    "prompt_chars": 700,
                    "current_request_preserved_rate": 1.0,
                },
            },
            {
                "group": "context_compression",
                "baseline": {"prompt_chars": 2000},
                "current": {
                    "prompt_chars": 1500,
                    "current_request_preserved_rate": 1.0,
                },
            },
        ]
    }
    metrics = compute_eval_metrics(result)
    assert metrics["context_case_count"] == 2
    assert metrics["avg_prompt_compression_rate"] == 0.275
    assert metrics["max_prompt_compression_rate"] == 0.3
    assert metrics["current_request_preserved_rate"] == 1.0


def test_load_eval_tasks_has_12_cases():
    tasks = load_eval_tasks()
    assert len(tasks) == 12
    assert {task["group"] for task in tasks} == {
        "context_compression",
        "memory_reuse",
        "checkpoint_resume",
    }


def test_run_eval_returns_baseline_current_cases():
    result = run_eval()
    data = result_to_dict(result)
    assert data["total"] == 12
    assert len(data["cases"]) == 12
    for case in data["cases"]:
        assert "baseline" in case
        assert "current" in case
        assert case["status"] == "PASS"
    assert "metrics" in data

    for case in data["cases"]:
        if case["group"] == "context_compression":
            assert case["baseline"]["prompt_chars"] > case["current"]["prompt_chars"]

    assert data["metrics"]["avg_prompt_compression_rate"] > 0
    assert data["metrics"]["max_prompt_compression_rate"] > 0


def test_eval_metrics_include_memory_and_resume():
    data = result_to_dict(run_eval())
    metrics = data["metrics"]
    assert metrics["total_eval_cases"] == 12
    assert metrics["context_case_count"] == 4
    assert metrics["memory_case_count"] == 4
    assert metrics["resume_case_count"] == 4
    assert metrics["baseline_followup_read_file_count"] > metrics["current_followup_read_file_count"]
    assert metrics["current_followup_read_file_count"] == 0
    assert metrics["resume_status_accuracy"] == 1.0
    assert metrics["workspace_drift_detection_rate"] == 1.0
    assert metrics["stale_state_safety_rate"] == 1.0

    memory_cases = [c for c in data["cases"] if c["group"] == "memory_reuse"]
    assert any(c["current"]["used_memory_summary"] for c in memory_cases)


def test_markdown_eval_summary_contains_resume_numbers():
    data = result_to_dict(run_eval())
    text = markdown_eval_summary(data)
    assert "Mico Ablation Evaluation Summary" in text
    assert "Average prompt compression" in text
    assert "Follow-up read_file reduction" in text
    assert "Workspace drift detection" in text
    assert "Resume status accuracy" in text
    assert "deterministic ablation benchmark" in text


def test_write_eval_results_creates_json_and_markdown(tmp_path):
    from benchmarks.eval_runner import write_eval_results
    result = run_eval()
    json_path = tmp_path / "eval-latest.json"
    md_path = tmp_path / "eval-latest.md"
    write_eval_results(result, json_path, md_path)

    assert json_path.exists()
    assert md_path.exists()
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["total"] == 12
    assert "metrics" in data
    text = md_path.read_text(encoding="utf-8")
    assert "简历候选表述" in text
