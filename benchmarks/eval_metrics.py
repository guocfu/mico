def compute_eval_metrics(result):
    cases = list(result.get("cases", []))
    context_cases = [c for c in cases if c.get("group") == "context_compression"]
    memory_cases = [c for c in cases if c.get("group") == "memory_reuse"]
    resume_cases = [c for c in cases if c.get("group") == "checkpoint_resume"]

    compression_rates = []
    preserved_rates = []
    for case in context_cases:
        baseline_chars = case.get("baseline", {}).get("prompt_chars", 0)
        current_chars = case.get("current", {}).get("prompt_chars", 0)
        if baseline_chars > 0:
            compression_rates.append(round((baseline_chars - current_chars) / baseline_chars, 4))
        preserved_rates.append(case.get("current", {}).get("current_request_preserved_rate", 0.0))

    repeated_before = sum(c.get("baseline", {}).get("followup_read_file_count", 0) for c in memory_cases)
    repeated_after = sum(c.get("current", {}).get("followup_read_file_count", 0) for c in memory_cases)

    resume_total = len(resume_cases)
    resume_correct = sum(
        1
        for c in resume_cases
        if c.get("current", {}).get("resume_status") == c.get("expected_resume_status")
    )
    drift_expected_cases = [
        c for c in resume_cases
        if c.get("expected_resume_status") not in (None, "full-valid")
    ]
    drift_detected = sum(
        1
        for c in drift_expected_cases
        if c.get("current", {}).get("drift_detected") is True
    )
    stale_safe = sum(
        1
        for c in resume_cases
        if not c.get("current", {}).get("trusted_stale_summary", False)
    )

    return {
        "total_eval_cases": len(cases),
        "context_case_count": len(context_cases),
        "memory_case_count": len(memory_cases),
        "resume_case_count": len(resume_cases),
        "avg_prompt_compression_rate": _avg(compression_rates),
        "max_prompt_compression_rate": max(compression_rates) if compression_rates else 0.0,
        "current_request_preserved_rate": _avg(preserved_rates),
        "baseline_followup_read_file_count": repeated_before,
        "current_followup_read_file_count": repeated_after,
        "followup_read_file_reduction": repeated_before - repeated_after,
        "resume_status_accuracy": round(resume_correct / resume_total, 4) if resume_total else 0.0,
        "workspace_drift_case_count": len(drift_expected_cases),
        "workspace_drift_detected_count": drift_detected,
        "workspace_drift_detection_rate": round(drift_detected / len(drift_expected_cases), 4) if drift_expected_cases else 0.0,
        "stale_state_safety_rate": round(stale_safe / resume_total, 4) if resume_total else 0.0,
    }


def markdown_eval_summary(result):
    metrics = compute_eval_metrics(result)
    lines = [
        "# Mico Ablation Evaluation Summary",
        "",
        "| Metric | Value |",
        "|---|---:|",
        "| Total eval cases | {} |".format(metrics["total_eval_cases"]),
        "| Average prompt compression | {} |".format(_percent(metrics["avg_prompt_compression_rate"])),
        "| Max prompt compression | {} |".format(_percent(metrics["max_prompt_compression_rate"])),
        "| Current request preserved | {} |".format(_percent(metrics["current_request_preserved_rate"])),
        "| Baseline follow-up read_file count | {} |".format(metrics["baseline_followup_read_file_count"]),
        "| Current follow-up read_file count | {} |".format(metrics["current_followup_read_file_count"]),
        "| Follow-up read_file reduction | {} |".format(metrics["followup_read_file_reduction"]),
        "| Resume status accuracy | {} |".format(_percent(metrics["resume_status_accuracy"])),
        "| Workspace drift detection | {} |".format(_percent(metrics["workspace_drift_detection_rate"])),
        "| Stale state safety rate | {} |".format(_percent(metrics["stale_state_safety_rate"])),
        "",
        "## 简历候选表述",
        "",
        "- 构建 {} 组 deterministic ablation benchmark，平均 prompt 压缩率 {}，最高压缩率 {}，follow-up 重复读文件次数从 {} 降到 {}，workspace 漂移识别率 {}，恢复状态识别准确率 {}。".format(
            metrics["total_eval_cases"],
            _percent(metrics["avg_prompt_compression_rate"]),
            _percent(metrics["max_prompt_compression_rate"]),
            metrics["baseline_followup_read_file_count"],
            metrics["current_followup_read_file_count"],
            _percent(metrics["workspace_drift_detection_rate"]),
            _percent(metrics["resume_status_accuracy"]),
        ),
        "",
        "---",
        "",
        "*主评测使用 FakeModelClient / prompt-aware fake model，不是 live model。*",
        "",
    ]
    return chr(10).join(lines)


def _avg(values):
    if not values:
        return 0.0
    return round(sum(values) / len(values), 4)


def _percent(value):
    return "{:.2f}%".format(value * 100)
