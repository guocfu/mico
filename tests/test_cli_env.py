from mico.cli import _resolve_config, build_agent, build_arg_parser
from mico.dotenv import load_dotenv
from mico.providers import FakeModelClient, OpenAICompatibleModelClient


def _parse(argv_str=""):
    return build_arg_parser().parse_args(argv_str.split() if argv_str else [])


def test_resolve_defaults_to_fake(monkeypatch):
    """No env, no .env, no CLI args → fake provider."""
    monkeypatch.delenv("MICO_API_KEY", raising=False)
    monkeypatch.delenv("MICO_BASE_URL", raising=False)
    monkeypatch.delenv("MICO_MODEL", raising=False)
    args = _parse("hello")
    provider, base_url, model, _ = _resolve_config(args)
    assert provider == "fake"
    assert base_url == ""
    assert model == ""


def test_resolve_auto_detects_openai_compatible(monkeypatch):
    """All three env vars set → auto-detect openai-compatible."""
    monkeypatch.setenv("MICO_API_KEY", "sk-test")
    monkeypatch.setenv("MICO_BASE_URL", "https://api.example.com")
    monkeypatch.setenv("MICO_MODEL", "gpt-4")
    args = _parse("hello")
    provider, base_url, model, _ = _resolve_config(args)
    assert provider == "openai-compatible"
    assert base_url == "https://api.example.com"
    assert model == "gpt-4"


def test_resolve_cli_provider_overrides_auto(monkeypatch):
    """Explicit --provider fake overrides auto-detection even with env set."""
    monkeypatch.setenv("MICO_API_KEY", "sk-test")
    monkeypatch.setenv("MICO_BASE_URL", "https://api.example.com")
    monkeypatch.setenv("MICO_MODEL", "gpt-4")
    args = _parse("hello --provider fake")
    provider, _, _, _ = _resolve_config(args)
    assert provider == "fake"


def test_resolve_cli_args_override_env(monkeypatch):
    """CLI --base-url and --model override env vars."""
    monkeypatch.setenv("MICO_API_KEY", "sk-test")
    monkeypatch.setenv("MICO_BASE_URL", "https://old.example.com")
    monkeypatch.setenv("MICO_MODEL", "gpt-3.5")
    args = _parse("hello --base-url https://new.example.com --model gpt-4")
    provider, base_url, model, _ = _resolve_config(args)
    assert provider == "openai-compatible"
    assert base_url == "https://new.example.com"
    assert model == "gpt-4"


def test_resolve_partial_env_stays_fake(monkeypatch):
    """Only API key set but missing base_url and model → stays fake."""
    monkeypatch.setenv("MICO_API_KEY", "sk-test")
    monkeypatch.delenv("MICO_BASE_URL", raising=False)
    monkeypatch.delenv("MICO_MODEL", raising=False)
    args = _parse("hello")
    provider, _, _, _ = _resolve_config(args)
    assert provider == "fake"


def test_complete_dotenv_auto_builds_openai_provider(monkeypatch, tmp_path):
    monkeypatch.delenv("MICO_API_KEY", raising=False)
    monkeypatch.delenv("MICO_BASE_URL", raising=False)
    monkeypatch.delenv("MICO_MODEL", raising=False)
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "MICO_API_KEY=sk-from-dotenv",
                "MICO_BASE_URL=https://api.example.com/v1",
                "MICO_MODEL=dotenv-model",
            ]
        ),
        encoding="utf-8",
    )

    load_dotenv(tmp_path)
    args = _parse(f"--cwd {tmp_path} hello")
    agent = build_agent(args)

    assert isinstance(agent.model_client, OpenAICompatibleModelClient)
    assert agent.model_client.base_url == "https://api.example.com/v1"
    assert agent.model_client.model == "dotenv-model"


def test_explicit_fake_provider_overrides_dotenv(monkeypatch, tmp_path):
    monkeypatch.setenv("MICO_API_KEY", "sk-from-env")
    monkeypatch.setenv("MICO_BASE_URL", "https://api.example.com/v1")
    monkeypatch.setenv("MICO_MODEL", "env-model")

    args = _parse(f"--cwd {tmp_path} hello --provider fake")
    agent = build_agent(args)

    assert isinstance(agent.model_client, FakeModelClient)


def test_default_approval_is_ask():
    args = _parse("hello")
    assert args.approval == "ask"


def test_approval_cli_override_auto():
    args = _parse("hello --approval auto")
    assert args.approval == "auto"


def test_approval_cli_override_never():
    args = _parse("hello --approval never")
    assert args.approval == "never"


def test_approval_choices_include_ask():
    args = _parse("hello")
    # Should not raise; "ask" is a valid choice
    assert args.approval in ("auto", "ask", "never")


# --- Task 5: CLI resume and session ID ---


def test_session_id_default():
    args = _parse("hello")
    assert args.session_id == "default"


def test_session_id_custom():
    args = _parse("hello --session-id custom")
    assert args.session_id == "custom"


def test_resume_custom():
    args = _parse("hello --resume custom")
    assert args.resume == "custom"


def test_resume_latest():
    args = _parse("hello --resume latest")
    assert args.resume == "latest"


def test_build_agent_with_session_id(tmp_path):
    args = _parse(f"--cwd {tmp_path} --session-id mysession hello")
    agent = build_agent(args)
    assert agent.session_id == "mysession"
    assert agent.resume_requested is False


def test_build_agent_with_resume(tmp_path):
    args = _parse(f"--cwd {tmp_path} --resume mysession hello")
    agent = build_agent(args)
    assert agent.session_id == "mysession"
    assert agent.resume_requested is True


def test_build_agent_resume_latest_with_sessions(tmp_path):
    """--resume latest uses the most recently modified session."""
    import time
    from mico.session_store import SessionStore

    ss = SessionStore(tmp_path / ".mico" / "sessions")
    ss.save("older", {"session_id": "older", "memory": {}})
    time.sleep(0.05)
    ss.save("newer", {"session_id": "newer", "memory": {}})

    args = _parse(f"--cwd {tmp_path} --resume latest hello")
    agent = build_agent(args)
    assert agent.session_id == "newer"
    assert agent.resume_requested is True


def test_build_agent_resume_latest_no_sessions(tmp_path):
    """--resume latest with no sessions falls back to 'default'."""
    args = _parse(f"--cwd {tmp_path} --resume latest hello")
    agent = build_agent(args)
    assert agent.session_id == "default"
    assert agent.resume_requested is True



def test_invalid_session_id_exits_cleanly(tmp_path):
    from mico.session_store import SessionStore
    args = _parse(f'--cwd {tmp_path} --session-id ../escape hello')
    try:
        build_agent(args)
        assert False, 'Expected SystemExit'
    except SystemExit:
        pass


def test_invalid_resume_id_exits_cleanly(tmp_path):
    from mico.session_store import SessionStore
    args = _parse(f'--cwd {tmp_path} --resume ../escape hello')
    try:
        build_agent(args)
        assert False, 'Expected SystemExit'
    except SystemExit:
        pass
