import json
from pathlib import Path

import pytest

from mico.providers import FakeModelClient
from mico.runtime import Mico
from mico.security import looks_sensitive_key, redact_artifact
from mico.state import RunStore
from mico.workspace import Workspace


class TestLooksSensitiveKey:
    def test_api_key(self):
        assert looks_sensitive_key("API_KEY") is True
        assert looks_sensitive_key("OPENAI_API_KEY") is True
        assert looks_sensitive_key("my_api_key") is True

    def test_token(self):
        assert looks_sensitive_key("TOKEN") is True
        assert looks_sensitive_key("ACCESS_TOKEN") is True

    def test_secret(self):
        assert looks_sensitive_key("SECRET") is True
        assert looks_sensitive_key("CLIENT_SECRET") is True

    def test_password(self):
        assert looks_sensitive_key("PASSWORD") is True
        assert looks_sensitive_key("DB_PASSWORD") is True

    def test_auth(self):
        assert looks_sensitive_key("AUTH") is True
        assert looks_sensitive_key("AUTHORIZATION") is True
        assert looks_sensitive_key("auth_token") is True
        assert looks_sensitive_key("basic_auth") is True

    def test_auth_not_false_positive(self):
        assert looks_sensitive_key("author") is False
        assert looks_sensitive_key("authority") is False
        assert looks_sensitive_key("authored") is False

    def test_normal_keys(self):
        assert looks_sensitive_key("PATH") is False
        assert looks_sensitive_key("HOME") is False
        assert looks_sensitive_key("USER") is False
        assert looks_sensitive_key("name") is False


class TestRedactArtifact:
    def test_sensitive_key_in_dict(self):
        result = redact_artifact({"api_key": "sk-abc123", "name": "test"})
        assert result["api_key"] == "[REDACTED]"
        assert result["name"] == "test"

    def test_nested_dict(self):
        result = redact_artifact({"config": {"token": "secret-val", "port": 8080}})
        assert result["config"]["token"] == "[REDACTED]"
        assert result["config"]["port"] == 8080

    def test_list_recursion(self):
        result = redact_artifact([{"secret": "val"}, "plain"])
        assert result[0]["secret"] == "[REDACTED]"
        assert result[1] == "plain"

    def test_tuple_recursion(self, monkeypatch):
        monkeypatch.setenv("MY_PASSWORD", "secret-pw")
        result = redact_artifact(("secret-pw", "data"))
        assert result == ("[REDACTED]", "data")

    def test_plain_string_unchanged(self):
        result = redact_artifact("hello world")
        assert result == "hello world"

    def test_plain_int_unchanged(self):
        result = redact_artifact(42)
        assert result == 42

    def test_env_secret_in_string_replaced(self, monkeypatch):
        monkeypatch.setenv("TEST_SECRET_VALUE", "super-secret-123")
        result = redact_artifact("found super-secret-123 in output")
        assert result == "found [REDACTED] in output"
        assert "super-secret-123" not in result

    def test_env_secret_not_in_string_when_absent(self, monkeypatch):
        monkeypatch.delenv("TEST_SECRET_VALUE", raising=False)
        result = redact_artifact("found super-secret-123 in output")
        assert result == "found super-secret-123 in output"


class TestTraceRedaction:
    def test_trace_redacts_sensitive_args(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MY_API_KEY", "sk-test-key-xyz")
        workspace = Workspace.build(tmp_path)
        agent = Mico(
            model_client=FakeModelClient([
                '<tool>{"name":"search","args":{"pattern":"sk-test-key-xyz","path":"."}}</tool>',
                "<final>done</final>",
            ]),
            workspace=workspace,
            run_store=RunStore(tmp_path / ".mico" / "runs"),
        )

        agent.ask("search for key")

        run_dirs = list((tmp_path / ".mico" / "runs").iterdir())
        trace_path = run_dirs[0] / "trace.jsonl"
        lines = trace_path.read_text(encoding="utf-8").strip().splitlines()
        full_text = "\n".join(lines)
        assert "sk-test-key-xyz" not in full_text
        assert "[REDACTED]" in full_text

    def test_trace_keeps_normal_data(self, tmp_path):
        workspace = Workspace.build(tmp_path)
        agent = Mico(
            model_client=FakeModelClient(["<final>ok</final>"]),
            workspace=workspace,
            run_store=RunStore(tmp_path / ".mico" / "runs"),
        )

        agent.ask("hello")

        run_dirs = list((tmp_path / ".mico" / "runs").iterdir())
        trace_path = run_dirs[0] / "trace.jsonl"
        lines = trace_path.read_text(encoding="utf-8").strip().splitlines()
        full_text = "\n".join(lines)
        assert "run_started" in full_text
        assert "hello" in full_text


class TestReportRedaction:
    def test_report_redacts_sensitive_fields(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MY_SECRET", "secret-val-999")
        workspace = Workspace.build(tmp_path)
        agent = Mico(
            model_client=FakeModelClient(["<final>done</final>"]),
            workspace=workspace,
            run_store=RunStore(tmp_path / ".mico" / "runs"),
        )

        agent.ask("task with secret-val-999")

        run_dirs = list((tmp_path / ".mico" / "runs").iterdir())
        report_path = run_dirs[0] / "report.json"
        report_text = report_path.read_text(encoding="utf-8")
        assert "secret-val-999" not in report_text
        assert "[REDACTED]" in report_text

    def test_report_keeps_normal_fields(self, tmp_path):
        workspace = Workspace.build(tmp_path)
        agent = Mico(
            model_client=FakeModelClient(["<final>ok</final>"]),
            workspace=workspace,
            run_store=RunStore(tmp_path / ".mico" / "runs"),
        )

        agent.ask("simple task")

        run_dirs = list((tmp_path / ".mico" / "runs").iterdir())
        report_path = run_dirs[0] / "report.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["history_items"] > 0
        assert "workspace_root" in report
        assert report["approval_policy"] == "auto"
        assert isinstance(report["available_tools"], list)
        assert isinstance(report["restricted_tools"], list)
        assert isinstance(report["tool_call_summary"], dict)
        assert report["artifacts_version"] == "1"
        assert report["failure_category"] == "success"
