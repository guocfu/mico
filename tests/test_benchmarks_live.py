import json

import pytest

from benchmarks.live import (
    LiveCaseResult,
    LiveResult,
    _check_config,
    _result_to_dict,
    run_live_smoke,
)


class _ScriptedLiveModelClient:
    def __init__(self, case):
        self.prompts = []
        tool = case["expected_tool"]
        if tool == "list_files":
            tool_output = '<tool>{"name":"list_files","args":{"path":"."}}</tool>'
        elif tool == "read_file":
            tool_output = '<tool>{"name":"read_file","args":{"path":"hello.txt"}}</tool>'
        elif tool == "search":
            tool_output = '<tool>{"name":"search","args":{"pattern":"hello","path":"."}}</tool>'
        else:
            raise AssertionError(f"unexpected tool: {tool}")
        self.outputs = [tool_output, "<final>done</final>"]

    def complete(self, prompt, *_args, **_kwargs):
        self.prompts.append(prompt)
        if not self.outputs:
            raise RuntimeError("scripted live model ran out of outputs")
        return self.outputs.pop(0)


class _RecordingFactory:
    def __init__(self):
        self.clients = []

    def __call__(self, case):
        client = _ScriptedLiveModelClient(case)
        self.clients.append(client)
        return client


def _fake_factory(case):
    return _ScriptedLiveModelClient(case)


class TestCheckConfig:
    def test_missing_all(self, monkeypatch):
        monkeypatch.delenv("MICO_API_KEY", raising=False)
        monkeypatch.delenv("MICO_BASE_URL", raising=False)
        monkeypatch.delenv("MICO_MODEL", raising=False)
        missing = _check_config()
        assert set(missing) == {"MICO_API_KEY", "MICO_BASE_URL", "MICO_MODEL"}

    def test_missing_one(self, monkeypatch):
        monkeypatch.setenv("MICO_API_KEY", "sk-test")
        monkeypatch.setenv("MICO_BASE_URL", "http://localhost")
        monkeypatch.delenv("MICO_MODEL", raising=False)
        missing = _check_config()
        assert missing == ["MICO_MODEL"]

    def test_all_present(self, monkeypatch):
        monkeypatch.setenv("MICO_API_KEY", "sk-test")
        monkeypatch.setenv("MICO_BASE_URL", "http://localhost")
        monkeypatch.setenv("MICO_MODEL", "gpt-4")
        assert _check_config() == []


class TestRunLiveSmoke:
    def test_missing_config_without_factory_raises(self, monkeypatch, tmp_path):
        monkeypatch.delenv("MICO_API_KEY", raising=False)
        monkeypatch.delenv("MICO_BASE_URL", raising=False)
        monkeypatch.delenv("MICO_MODEL", raising=False)

        with pytest.raises(ValueError, match="missing required config"):
            run_live_smoke(results_path=tmp_path / "live-latest.json")

    def test_writes_results_json(self, tmp_path):
        results_path = tmp_path / "results" / "live-latest.json"
        result = run_live_smoke(model_client_factory=_fake_factory, results_path=results_path)

        assert results_path.exists()
        data = json.loads(results_path.read_text(encoding="utf-8"))
        assert data["total"] == 3
        assert data["passed"] == 3
        assert data["failed"] == 0
        assert len(data["cases"]) == 3

    def test_all_cases_pass_with_fake(self, tmp_path):
        results_path = tmp_path / "results" / "live-latest.json"
        result = run_live_smoke(model_client_factory=_fake_factory, results_path=results_path)

        assert result.total == 3
        assert result.passed == 3
        assert result.failed == 0
        for case in result.cases:
            assert case.status == "PASS"
            assert case.run_id
            assert case.stop_reason == "final"
            assert case.failure_category == "success"

    def test_results_no_prompt_or_raw_output(self, tmp_path):
        results_path = tmp_path / "results" / "live-latest.json"
        run_live_smoke(model_client_factory=_fake_factory, results_path=results_path)

        text = results_path.read_text(encoding="utf-8")
        assert "Tool result from" not in text
        assert "<tool>" not in text
        assert "<final>" not in text

    def test_results_no_api_key(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MICO_API_KEY", "sk-secret-key-leak-test")
        results_path = tmp_path / "results" / "live-latest.json"
        run_live_smoke(model_client_factory=_fake_factory, results_path=results_path)

        text = results_path.read_text(encoding="utf-8")
        assert "sk-secret-key-leak-test" not in text

    def test_default_approval_never(self, tmp_path):
        """Verify live prompts are built under approval_policy=never."""
        factory = _RecordingFactory()
        results_path = tmp_path / "results" / "live-latest.json"
        result = run_live_smoke(model_client_factory=factory, results_path=results_path)

        assert result.passed == 3
        assert factory.clients
        for client in factory.clients:
            assert any("Approval policy: never" in prompt for prompt in client.prompts)

    def test_approval_never_in_report(self, tmp_path):
        """Verify approval_policy=never is recorded in run artifacts."""
        from mico.providers import FakeModelClient
        from mico.runtime import Mico
        from mico.state import RunStore
        from mico.workspace import Workspace

        ws_root = tmp_path / "ws"
        ws_root.mkdir()
        (ws_root / "hello.txt").write_text("hello\n", encoding="utf-8")
        workspace = Workspace.build(ws_root)
        runs_dir = ws_root / ".mico" / "runs"
        agent = Mico(
            model_client=FakeModelClient(),
            workspace=workspace,
            run_store=RunStore(runs_dir),
            approval_policy="never",
            max_steps=4,
        )
        agent.ask("List files.")
        run_dir = list(runs_dir.iterdir())[0]
        report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
        assert report["approval_policy"] == "never"

    def test_case_result_structure(self, tmp_path):
        results_path = tmp_path / "results" / "live-latest.json"
        run_live_smoke(model_client_factory=_fake_factory, results_path=results_path)

        data = json.loads(results_path.read_text(encoding="utf-8"))
        for case in data["cases"]:
            assert "name" in case
            assert "status" in case
            assert "run_id" in case
            assert "stop_reason" in case
            assert "failure_category" in case
            assert "errors" in case

    def test_failing_factory_reports_error(self, tmp_path):
        def bad_factory():
            raise RuntimeError("connection refused")

        results_path = tmp_path / "results" / "live-latest.json"
        result = run_live_smoke(model_client_factory=bad_factory, results_path=results_path)

        assert result.failed == 3
        for case in result.cases:
            assert case.status == "ERROR"
            assert "connection refused" in case.errors[0]

    def test_expected_tool_mismatch_fails_case(self, tmp_path):
        class WrongToolClient:
            def __init__(self):
                self.outputs = [
                    '<tool>{"name":"list_files","args":{"path":"."}}</tool>',
                    "<final>done</final>",
                ]

            def complete(self, _prompt, *_args, **_kwargs):
                return self.outputs.pop(0)

        def wrong_factory(_case):
            return WrongToolClient()

        result = run_live_smoke(
            model_client_factory=wrong_factory,
            results_path=tmp_path / "results" / "live-latest.json",
        )

        read_case = next(case for case in result.cases if case.name == "read_file")
        search_case = next(case for case in result.cases if case.name == "search")
        assert read_case.status == "FAIL"
        assert search_case.status == "FAIL"
        assert "expected tool" in read_case.errors[0]


class TestResultToDict:
    def test_structure(self):
        result = LiveResult(total=1, passed=1, failed=0)
        result.cases = [
            LiveCaseResult("test", "PASS", "abc123", "final", "success", []),
        ]
        data = _result_to_dict(result)
        assert data["total"] == 1
        assert data["passed"] == 1
        assert data["failed"] == 0
        assert len(data["cases"]) == 1
        assert data["cases"][0]["name"] == "test"
        assert data["cases"][0]["errors"] == []

    def test_json_serializable(self):
        result = LiveResult(total=0, passed=0, failed=0)
        data = _result_to_dict(result)
        text = json.dumps(data)
        assert isinstance(text, str)
