import pytest

from mico.cli import main


class FakeAgent:
    def __init__(self):
        self.ask_calls = []

    def ask(self, message):
        self.ask_calls.append(message)
        return f"echo: {message}"


def _patch_build_agent(monkeypatch, fake_agent):
    monkeypatch.setattr("mico.cli.build_agent", lambda args: fake_agent)


# --- REPL entry ---

def _make_input_side_effect(values):
    """Return a callable that yields values then raises EOFError.

    If a value is an Exception subclass or instance, it is raised instead of returned.
    """
    it = iter(values)

    def _input(_prompt=""):
        val = next(it)
        if isinstance(val, BaseException):
            raise val
        if isinstance(val, type) and issubclass(val, BaseException):
            raise val()
        return val

    return _input


def test_main_no_prompt_enters_repl(monkeypatch, capsys):
    """main([]) enters REPL; one input then EOF -> ask called once, output contains answer."""
    fake = FakeAgent()
    _patch_build_agent(monkeypatch, fake)
    monkeypatch.setattr("builtins.input", _make_input_side_effect(["hello world", EOFError()]))
    result = main([])
    assert result == 0
    assert fake.ask_calls == ["hello world"]
    captured = capsys.readouterr()
    assert "echo: hello world" in captured.out


# --- Empty input skip ---

def test_repl_empty_input_skipped(monkeypatch, capsys):
    """Blank input is skipped, does not call ask."""
    fake = FakeAgent()
    _patch_build_agent(monkeypatch, fake)
    monkeypatch.setattr("builtins.input", _make_input_side_effect(["", "   ", "real", EOFError()]))
    result = main([])
    assert result == 0
    assert fake.ask_calls == ["real"]
    captured = capsys.readouterr()
    assert "echo: real" in captured.out


# --- Exit signals ---

def test_repl_eof_exits_zero(monkeypatch, capsys):
    """EOFError on first input -> exit 0, Bye printed."""
    fake = FakeAgent()
    _patch_build_agent(monkeypatch, fake)
    monkeypatch.setattr("builtins.input", _make_input_side_effect([EOFError()]))
    result = main([])
    assert result == 0
    captured = capsys.readouterr()
    assert "Bye" in captured.out


def test_repl_keyboard_interrupt_exits_zero(monkeypatch, capsys):
    """KeyboardInterrupt -> exit 0, Bye printed."""
    fake = FakeAgent()
    _patch_build_agent(monkeypatch, fake)
    monkeypatch.setattr("builtins.input", _make_input_side_effect([KeyboardInterrupt()]))
    result = main([])
    assert result == 0
    captured = capsys.readouterr()
    assert "Bye" in captured.out


# --- --verify-cmd with no prompt ---

def test_verify_cmd_without_prompt_raises(monkeypatch):
    """--verify-cmd with no prompt raises SystemExit mentioning 'one-shot mode'."""
    with pytest.raises(SystemExit, match="one-shot mode"):
        main(["--verify-cmd", "python verify.py"])


# --- One-shot behavior preserved ---

def test_main_with_prompt_one_shot(monkeypatch, capsys):
    """main(['hello']) calls ask once and prints the answer."""
    fake = FakeAgent()
    _patch_build_agent(monkeypatch, fake)
    result = main(["hello"])
    assert result == 0
    assert fake.ask_calls == ["hello"]
    captured = capsys.readouterr()
    assert "echo: hello" in captured.out
