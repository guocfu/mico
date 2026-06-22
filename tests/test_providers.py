import json
from unittest.mock import MagicMock, patch

import pytest

from mico.cli import build_arg_parser, build_agent
from mico.providers import FakeModelClient, OpenAICompatibleModelClient


class TestOpenAICompatibleModelClient:
    def test_from_env_raises_when_key_missing(self, monkeypatch):
        monkeypatch.delenv("MICO_API_KEY", raising=False)
        with pytest.raises(ValueError, match="MICO_API_KEY"):
            OpenAICompatibleModelClient.from_env(
                base_url="http://localhost:8000/v1",
                model="test-model",
            )

    def test_from_env_raises_when_custom_key_env_missing(self, monkeypatch):
        monkeypatch.delenv("MY_KEY", raising=False)
        with pytest.raises(ValueError, match="MY_KEY"):
            OpenAICompatibleModelClient.from_env(
                base_url="http://localhost:8000/v1",
                model="test-model",
                api_key_env="MY_KEY",
            )

    def test_from_env_succeeds_with_key(self, monkeypatch):
        monkeypatch.setenv("MICO_API_KEY", "sk-test-123")
        client = OpenAICompatibleModelClient.from_env(
            base_url="http://localhost:8000/v1",
            model="test-model",
        )
        assert client.model == "test-model"
        assert client.base_url == "http://localhost:8000/v1"
        assert client.timeout == 120

    def test_from_env_custom_timeout(self, monkeypatch):
        monkeypatch.setenv("MICO_API_KEY", "sk-test")
        client = OpenAICompatibleModelClient.from_env(
            base_url="http://localhost:8000/v1",
            model="m",
            timeout=30,
        )
        assert client.timeout == 30

    @patch("urllib.request.urlopen")
    def test_complete_sends_request(self, mock_urlopen, monkeypatch):
        monkeypatch.setenv("MICO_API_KEY", "sk-test")
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(
            {"choices": [{"message": {"content": "<final>hello</final>"}}]}
        ).encode("utf-8")
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        client = OpenAICompatibleModelClient.from_env(
            base_url="http://localhost:8000/v1",
            model="test-model",
        )
        result = client.complete("test prompt")

        assert result == "<final>hello</final>"
        assert len(client.prompts) == 1
        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        assert req.full_url == "http://localhost:8000/v1/chat/completions"
        assert req.get_header("Authorization") == "Bearer sk-test"
        body = json.loads(req.data.decode("utf-8"))
        assert body["model"] == "test-model"
        assert body["messages"] == [{"role": "user", "content": "test prompt"}]

    @patch("urllib.request.urlopen")
    def test_complete_raises_on_bad_response(self, mock_urlopen, monkeypatch):
        monkeypatch.setenv("MICO_API_KEY", "sk-test")
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"unexpected": True}).encode("utf-8")
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        client = OpenAICompatibleModelClient.from_env(
            base_url="http://localhost:8000/v1",
            model="test-model",
        )
        with pytest.raises(RuntimeError, match="unexpected model response format"):
            client.complete("test")


class TestCLIProviderArgs:
    def test_default_provider_is_fake(self):
        parser = build_arg_parser()
        args = parser.parse_args(["hello"])
        assert args.provider == "fake"
        assert args.model == ""
        assert args.base_url == ""
        assert args.api_key_env == "MICO_API_KEY"
        assert args.model_timeout == 120

    def test_parse_openai_compatible_args(self):
        parser = build_arg_parser()
        args = parser.parse_args([
            "hello",
            "--provider", "openai-compatible",
            "--model", "gpt-4",
            "--base-url", "http://localhost:8000/v1",
            "--api-key-env", "MY_KEY",
            "--model-timeout", "30",
        ])
        assert args.provider == "openai-compatible"
        assert args.model == "gpt-4"
        assert args.base_url == "http://localhost:8000/v1"
        assert args.api_key_env == "MY_KEY"
        assert args.model_timeout == 30

    def test_build_agent_default_fake(self, tmp_path):
        args = build_arg_parser().parse_args(["--cwd", str(tmp_path), "hello"])
        agent = build_agent(args)
        assert isinstance(agent.model_client, FakeModelClient)

    @patch("urllib.request.urlopen")
    def test_build_agent_openai_compatible(self, mock_urlopen, tmp_path, monkeypatch):
        monkeypatch.setenv("MICO_API_KEY", "sk-test")
        args = build_arg_parser().parse_args([
            "--cwd", str(tmp_path),
            "--provider", "openai-compatible",
            "--model", "gpt-4",
            "--base-url", "http://localhost:8000/v1",
            "hello",
        ])
        agent = build_agent(args)
        assert isinstance(agent.model_client, OpenAICompatibleModelClient)
        assert agent.model_client.model == "gpt-4"

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(
            {"choices": [{"message": {"content": "<final>ok</final>"}}]}
        ).encode("utf-8")
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        agent.model_client.complete("test")
        req = mock_urlopen.call_args[0][0]
        assert req.get_header("Authorization") == "Bearer sk-test"

    def test_build_agent_openai_missing_base_url(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MICO_API_KEY", "sk-test")
        args = build_arg_parser().parse_args([
            "--cwd", str(tmp_path),
            "--provider", "openai-compatible",
            "--model", "gpt-4",
            "hello",
        ])
        with pytest.raises(SystemExit, match="--base-url"):
            build_agent(args)

    def test_build_agent_openai_missing_model(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MICO_API_KEY", "sk-test")
        args = build_arg_parser().parse_args([
            "--cwd", str(tmp_path),
            "--provider", "openai-compatible",
            "--base-url", "http://localhost:8000/v1",
            "hello",
        ])
        with pytest.raises(SystemExit, match="--model"):
            build_agent(args)

    def test_build_agent_openai_missing_api_key(self, tmp_path, monkeypatch):
        monkeypatch.delenv("MICO_API_KEY", raising=False)
        args = build_arg_parser().parse_args([
            "--cwd", str(tmp_path),
            "--provider", "openai-compatible",
            "--model", "gpt-4",
            "--base-url", "http://localhost:8000/v1",
            "hello",
        ])
        with pytest.raises(SystemExit, match="MICO_API_KEY"):
            build_agent(args)
