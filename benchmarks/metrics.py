def compute_metrics(result):
    total = result.total
    passed = result.passed
    failed = result.failed
    cases = list(result.cases)

    artifacts_complete = sum(1 for case in cases if case.artifacts_complete)
    attributed = sum(1 for case in cases if case.failure_category and case.failure_category != "unknown")
    parser_retry_count_total = sum(case.parser_retry_count for case in cases)

    governance_cases = [case for case in cases if case.group == "tool_governance"]
    governance_passed = sum(1 for case in governance_cases if case.status == "PASS")

    verification_cases = [case for case in cases if case.verification_ok is not None]
    verification_passed = sum(1 for case in verification_cases if case.verification_ok)

    closure_cases = [case for case in cases if case.group == "task_closure"]
    closure_passed = sum(1 for case in closure_cases if case.status == "PASS")

    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "pass_rate": _ratio(passed, total),
        "artifact_completeness_rate": _ratio(artifacts_complete, total),
        "failure_attribution_coverage": _ratio(attributed, total),
        "tool_guard_pass_rate": _ratio(governance_passed, len(governance_cases)),
        "tool_governance_total": len(governance_cases),
        "parser_retry_count_total": parser_retry_count_total,
        "verifier_pass_rate": _ratio(verification_passed, len(verification_cases)),
        "verification_total": len(verification_cases),
        "task_closure_pass_rate": _ratio(closure_passed, len(closure_cases)),
        "task_closure_total": len(closure_cases),
    }


def markdown_summary(result):
    metrics = compute_metrics(result)
    lines = [
        "# Mico Benchmark Summary",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Total cases | {metrics['total']} |",
        f"| Passed | {metrics['passed']} |",
        f"| Failed | {metrics['failed']} |",
        f"| Pass rate | {_percent(metrics['pass_rate'])} |",
        f"| Artifact completeness | {_percent(metrics['artifact_completeness_rate'])} |",
        f"| Failure attribution coverage | {_percent(metrics['failure_attribution_coverage'])} |",
        f"| Tool guard pass rate | {_percent(metrics['tool_guard_pass_rate'])} |",
        f"| Verifier pass rate | {_percent(metrics['verifier_pass_rate'])} |",
        f"| Task closure pass rate | {_percent(metrics['task_closure_pass_rate'])} |",
        f"| Parser retry count | {metrics['parser_retry_count_total']} |",
        "",
        "| Case | Group | Status | Stop reason | Failure category | Parser retries |",
        "|---|---|---|---|---|---:|",
    ]
    for case in result.cases:
        lines.append(
            f"| {case.name} | {case.group} | {case.status} | "
            f"{case.stop_reason} | {case.failure_category} | {case.parser_retry_count} |"
        )
    lines.append("")
    return "\n".join(lines)


def _ratio(numerator, denominator):
    if denominator == 0:
        return 0.0
    return round(numerator / denominator, 4)


def _percent(value):
    return f"{value * 100:.2f}%"
