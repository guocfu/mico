"""Manual smoke runner for the real OpenAI-compatible provider.

Usage: python -m benchmarks.live

Requires MICO_API_KEY, MICO_BASE_URL, MICO_MODEL in .env or system env.
Only runs read-only tool cases. Does not run as part of default tests.
"""

import json
import os
import shutil
import sys
import uuid
from dataclasses import dataclass, field
from inspect import signature
from pathlib import Path

from mico.dotenv import load_dotenv
from mico.runtime import Mico
from mico.security import redact_artifact
from mico.state import RunStore
from mico.workspace import clip
from mico.workspace import Workspace


@dataclass
class LiveCaseResult:
    name: str
    status: str
    run_id: str
    stop_reason: str
    failure_category: str
    errors: list = field(default_factory=list)


@dataclass
class LiveResult:
    total: int
    passed: int
    failed: int
    cases: list = field(default_factory=list)


_LIVE_SMOKE_CASES = [
    {
        "name": "list_files",
        "expected_tool": "list_files",
        "user_message": 'Use the list_files tool with path ".". Then summarize the files.',
    },
    {
        "name": "read_file",
        "expected_tool": "read_file",
        "user_message": "Use the read_file tool to read hello.txt. Then summarize the file.",
    },
    {
        "name": "search",
        "expected_tool": "search",
        "user_message": 'Use the search tool for pattern "hello" in path ".". Then summarize the match.',
    },
    {
        "name": "create_and_verify_python_task",
        "expected_tools": ["write_file", "run_command"],
        "approval_policy": "auto",
        "setup_verify_py": True,
        "user_message": (
            "Create src/fibonacci.py implementing fib(n) with fib(0)=0, fib(1)=1, "
            "fib(n)=fib(n-1)+fib(n-2) for n>=2. "
            "Then run the command: python verify.py"
        ),
    },
]

_REQUIRED_KEYS = ("MICO_API_KEY", "MICO_BASE_URL", "MICO_MODEL")

_TEMP_ROOT = Path(__file__).resolve().parent.parent / ".tmp" / "benchmarks" / "live"
_DEFAULT_RESULTS_PATH = Path(__file__).resolve().parent / "results" / "live-latest.json"


def _check_config():
    """Return list of missing config key names."""
    return [k for k in _REQUIRED_KEYS if not os.environ.get(k)]


def _config_error(missing):
    return f"missing required config: {', '.join(missing)}"


def _default_model_client_factory():
    from mico.providers import OpenAICompatibleModelClient

    return OpenAICompatibleModelClient(
        base_url=os.environ["MICO_BASE_URL"],
        model=os.environ["MICO_MODEL"],
        api_key=os.environ["MICO_API_KEY"],
    )


def _setup_workspace(root):
    """Create a tiny workspace with a known file for smoke cases."""
    (root / "hello.txt").write_text("hello world\n", encoding="utf-8")


def _setup_verify_py(root):
    """Create verify.py for writable coding task cases."""
    (root / "verify.py").write_text(
        "import sys, os\n"
        "sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))\n"
        "from fibonacci import fib\n"
        "assert fib(0) == 0\n"
        "assert fib(1) == 1\n"
        "assert fib(10) == 55\n"
        "print('ALL TESTS PASSED')\n",
        encoding="utf-8",
    )


def _safe_error(exc):
    message = str(exc)
    if "unexpected model response format" in message:
        message = "unexpected model response format"
    message = redact_artifact(message)
    return clip(f"{type(exc).__name__}: {message}", 240)


def _make_model_client(model_client_factory, case):
    try:
        params = signature(model_client_factory).parameters
    except (TypeError, ValueError):
        params = {}
    if not params:
        return model_client_factory()
    return model_client_factory(case)


def _result_to_dict(result):
    return {
        "total": result.total,
        "passed": result.passed,
        "failed": result.failed,
        "cases": [
            {
                "name": c.name,
                "status": c.status,
                "run_id": c.run_id,
                "stop_reason": c.stop_reason,
                "failure_category": c.failure_category,
                "errors": c.errors,
            }
            for c in result.cases
        ],
    }


def _is_ordered_subsequence(expected, actual):
    """Return True if *expected* is an ordered subsequence of *actual*."""
    it = iter(actual)
    return all(any(a == e for a in it) for e in expected)


def _run_case(case, model_client_factory):
    """Run a single smoke case in a fresh temp workspace. Returns LiveCaseResult."""
    _TEMP_ROOT.mkdir(parents=True, exist_ok=True)
    ws_root = _TEMP_ROOT / f"{case['name']}-{uuid.uuid4().hex[:8]}"
    ws_root.mkdir(parents=True, exist_ok=False)
    try:
        workspace = Workspace.build(ws_root)
        runs_dir = ws_root / ".mico" / "runs"
        _setup_workspace(ws_root)

        if case.get("setup_verify_py"):
            _setup_verify_py(ws_root)

        approval_policy = case.get("approval_policy", "never")
        max_steps = case.get("max_steps", 4)
        model_client = _make_model_client(model_client_factory, case)
        agent = Mico(
            model_client=model_client,
            workspace=workspace,
            run_store=RunStore(runs_dir),
            approval_policy=approval_policy,
            max_steps=max_steps,
        )

        agent.ask(case["user_message"])

        run_dirs = list(runs_dir.iterdir())
        if len(run_dirs) != 1:
            return LiveCaseResult(
                name=case["name"],
                status="ERROR",
                run_id="",
                stop_reason="",
                failure_category="",
                errors=[f"expected 1 run dir, got {len(run_dirs)}"],
            )

        run_dir = run_dirs[0]
        report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
        state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))

        errors = []
        stop_reason = state.get("stop_reason", "")
        failure_category = report.get("failure_category", "")

        if stop_reason != "final":
            errors.append(f"stop_reason={stop_reason}, expected final")
        if failure_category != "success":
            errors.append(f"failure_category={failure_category}, expected success")
        tools = state.get("tools", [])
        if "expected_tools" in case:
            expected_tools = case["expected_tools"]
            if not _is_ordered_subsequence(expected_tools, tools):
                errors.append(f"expected tools {expected_tools} as ordered subsequence, got {tools}")
            if "run_command" in expected_tools:
                history_text = json.dumps(agent.history, ensure_ascii=False)
                if "ALL TESTS PASSED" not in history_text:
                    errors.append("verification failed: 'ALL TESTS PASSED' not in history")
        else:
            expected_tool = case["expected_tool"]
            if expected_tool not in tools:
                errors.append(f"expected tool {expected_tool!r} to be used, got {tools!r}")
        expected_approval = case.get("approval_policy", "never")
        if report.get("approval_policy") != expected_approval:
            errors.append(f"approval_policy={report.get('approval_policy')}, expected {expected_approval}")

        return LiveCaseResult(
            name=case["name"],
            status="PASS" if not errors else "FAIL",
            run_id=run_dir.name,
            stop_reason=stop_reason,
            failure_category=failure_category,
            errors=errors,
        )
    except Exception as exc:
        return LiveCaseResult(
            name=case["name"],
            status="ERROR",
            run_id="",
            stop_reason="",
            failure_category="",
            errors=[_safe_error(exc)],
        )
    finally:
        shutil.rmtree(ws_root, ignore_errors=True)


def run_live_smoke(model_client_factory=None, results_path=None):
    """Run live smoke cases and return LiveResult.

    Args:
        model_client_factory: callable returning a model client instance.
            Defaults to creating OpenAICompatibleModelClient from env.
        results_path: path to write results JSON. Defaults to benchmarks/results/live-latest.json.
    """
    if model_client_factory is None:
        missing = _check_config()
        if missing:
            raise ValueError(_config_error(missing))
        model_client_factory = _default_model_client_factory
    if results_path is None:
        results_path = _DEFAULT_RESULTS_PATH

    result = LiveResult(total=len(_LIVE_SMOKE_CASES), passed=0, failed=0)

    for case in _LIVE_SMOKE_CASES:
        case_result = _run_case(case, model_client_factory)
        result.cases.append(case_result)
        if case_result.status == "PASS":
            result.passed += 1
        else:
            result.failed += 1

    results_path = Path(results_path)
    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(
        json.dumps(_result_to_dict(result), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return result


def _print_summary(result):
    for case in result.cases:
        marker = "PASS" if case.status == "PASS" else case.status
        print(f"  [{marker}] {case.name}")
        if case.errors:
            for err in case.errors:
                print(f"         {err}")
    print(f"\n{result.passed}/{result.total} passed, {result.failed} failed")


def main():
    load_dotenv(Path.cwd())
    missing = _check_config()
    if missing:
        print(f"Error: {_config_error(missing)}", file=sys.stderr)
        print("Set these in .env or as environment variables.", file=sys.stderr)
        sys.exit(1)

    result = run_live_smoke()
    _print_summary(result)
    print(f"\nResults written to {_DEFAULT_RESULTS_PATH}")
    sys.exit(0 if result.failed == 0 else 1)


if __name__ == "__main__":
    main()
