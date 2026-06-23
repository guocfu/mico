import os
import textwrap
from pathlib import Path

from mico.dotenv import load_dotenv, parse_dotenv


def test_parse_basic_key_value(tmp_path):
    f = tmp_path / ".env"
    f.write_text("MICO_API_KEY=sk-test123\n")
    assert parse_dotenv(f) == {"MICO_API_KEY": "sk-test123"}


def test_parse_export_prefix(tmp_path):
    f = tmp_path / ".env"
    f.write_text("export MICO_API_KEY=sk-test\n")
    assert parse_dotenv(f) == {"MICO_API_KEY": "sk-test"}


def test_parse_double_quotes(tmp_path):
    f = tmp_path / ".env"
    f.write_text('MICO_BASE_URL="https://api.example.com"\n')
    assert parse_dotenv(f) == {"MICO_BASE_URL": "https://api.example.com"}


def test_parse_single_quotes(tmp_path):
    f = tmp_path / ".env"
    f.write_text("MICO_MODEL='gpt-4'\n")
    assert parse_dotenv(f) == {"MICO_MODEL": "gpt-4"}


def test_parse_comments_and_blanks(tmp_path):
    f = tmp_path / ".env"
    f.write_text(textwrap.dedent("""\
        # this is a comment
        MICO_API_KEY=sk-abc

        # another comment
        MICO_MODEL=gpt-4
    """))
    result = parse_dotenv(f)
    assert result == {"MICO_API_KEY": "sk-abc", "MICO_MODEL": "gpt-4"}


def test_parse_ignores_unknown_keys(tmp_path):
    f = tmp_path / ".env"
    f.write_text(textwrap.dedent("""\
        MICO_API_KEY=sk-abc
        MICO_PROVIDER=openai-compatible
        MICO_MODEL_TIMEOUT=30
        SOME_OTHER_KEY=ignored
        DATABASE_URL=also-ignored
    """))
    result = parse_dotenv(f)
    assert result == {"MICO_API_KEY": "sk-abc"}


def test_parse_all_three_keys(tmp_path):
    f = tmp_path / ".env"
    f.write_text(textwrap.dedent("""\
        MICO_API_KEY=sk-abc
        MICO_BASE_URL=https://api.example.com
        MICO_MODEL=gpt-4
    """))
    result = parse_dotenv(f)
    assert result == {
        "MICO_API_KEY": "sk-abc",
        "MICO_BASE_URL": "https://api.example.com",
        "MICO_MODEL": "gpt-4",
    }


def test_parse_missing_file(tmp_path):
    result = parse_dotenv(tmp_path / "nonexistent.env")
    assert result == {}


def test_parse_value_with_equals_sign(tmp_path):
    f = tmp_path / ".env"
    f.write_text("MICO_BASE_URL=https://api.example.com/v1\n")
    result = parse_dotenv(f)
    assert result == {"MICO_BASE_URL": "https://api.example.com/v1"}


def test_parse_whitespace_around_key_and_value(tmp_path):
    f = tmp_path / ".env"
    f.write_text("  MICO_API_KEY  =  sk-test  \n")
    result = parse_dotenv(f)
    assert result == {"MICO_API_KEY": "sk-test"}


def test_load_dotenv_does_not_override_env(monkeypatch, tmp_path):
    monkeypatch.setenv("MICO_API_KEY", "sk-from-env")
    f = tmp_path / ".env"
    f.write_text("MICO_API_KEY=sk-from-file\n")
    injected = load_dotenv(tmp_path)
    assert injected == {}
    assert os.environ["MICO_API_KEY"] == "sk-from-env"


def test_load_dotenv_injects_missing_keys(monkeypatch, tmp_path):
    monkeypatch.delenv("MICO_API_KEY", raising=False)
    monkeypatch.delenv("MICO_BASE_URL", raising=False)
    monkeypatch.delenv("MICO_MODEL", raising=False)
    f = tmp_path / ".env"
    f.write_text(textwrap.dedent("""\
        MICO_API_KEY=sk-from-file
        MICO_BASE_URL=https://example.com
        MICO_MODEL=gpt-4
    """))
    injected = load_dotenv(tmp_path)
    assert injected == {
        "MICO_API_KEY": "sk-from-file",
        "MICO_BASE_URL": "https://example.com",
        "MICO_MODEL": "gpt-4",
    }
    assert os.environ["MICO_API_KEY"] == "sk-from-file"
    assert os.environ["MICO_BASE_URL"] == "https://example.com"
    assert os.environ["MICO_MODEL"] == "gpt-4"


def test_load_dotenv_mixed_override(monkeypatch, tmp_path):
    """System env overrides .env for keys that exist; .env fills the rest."""
    monkeypatch.setenv("MICO_API_KEY", "sk-system")
    monkeypatch.delenv("MICO_BASE_URL", raising=False)
    monkeypatch.delenv("MICO_MODEL", raising=False)
    f = tmp_path / ".env"
    f.write_text(textwrap.dedent("""\
        MICO_API_KEY=sk-file
        MICO_BASE_URL=https://example.com
        MICO_MODEL=gpt-4
    """))
    injected = load_dotenv(tmp_path)
    assert "MICO_API_KEY" not in injected
    assert injected["MICO_BASE_URL"] == "https://example.com"
    assert injected["MICO_MODEL"] == "gpt-4"
    assert os.environ["MICO_API_KEY"] == "sk-system"
