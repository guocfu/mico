import json
import sys

import pytest

from mico.verification import VerificationResult, run_verification, write_verification_json


def test_run_verification_success(tmp_path):
    script = tmp_path / "pass.py"
    script.write_text("print('ok')", encoding="utf-8")

    result = run_verification(tmp_path, f"{sys.executable} pass.py")

    assert result.ok is True
    assert result.exit_code == 0
    assert result.timed_out is False
    assert "ok" in result.stdout_tail
    assert result.command.endswith("pass.py")
    assert result.argv == [sys.executable, "pass.py"]
    assert result.duration_ms >= 0


def test_run_verification_failure(tmp_path):
    script = tmp_path / "fail.py"
    script.write_text("import sys; sys.exit(1)", encoding="utf-8")

    result = run_verification(tmp_path, f"{sys.executable} fail.py")

    assert result.ok is False
    assert result.exit_code == 1
    assert result.timed_out is False


def test_run_verification_timeout(tmp_path):
    script = tmp_path / "slow.py"
    script.write_text("import time; time.sleep(60)", encoding="utf-8")

    result = run_verification(tmp_path, f"{sys.executable} slow.py", timeout=1)

    assert result.ok is False
    assert result.exit_code == -1
    assert result.timed_out is True
    assert result.duration_ms < 5000


def test_run_verification_empty_cmd_raises(tmp_path):
    with pytest.raises(ValueError, match="verify_cmd must not be empty"):
        run_verification(tmp_path, "")


def test_run_verification_empty_argv_list_raises(tmp_path):
    with pytest.raises(ValueError, match="verify_cmd must not be empty"):
        run_verification(tmp_path, [])


def test_run_verification_argv_list(tmp_path):
    script = tmp_path / "echo.py"
    script.write_text("print('hello')", encoding="utf-8")

    result = run_verification(tmp_path, [sys.executable, "echo.py"])

    assert result.ok is True
    assert result.argv == [sys.executable, "echo.py"]
    assert "hello" in result.stdout_tail


def test_run_verification_argv_list_bypasses_shlex(tmp_path):
    """argv list should be used directly, not re-parsed by shlex."""
    script = tmp_path / "args.py"
    script.write_text(
        "import sys; print('|'.join(sys.argv[1:]))",
        encoding="utf-8",
    )

    result = run_verification(
        tmp_path,
        [sys.executable, "args.py", "hello world", "two"],
    )

    assert result.ok is True
    assert "hello world|two" in result.stdout_tail


def test_run_verification_long_output_truncated(tmp_path):
    """stdout exceeding 2000 chars should be truncated to the last 2000."""
    script = tmp_path / "long.py"
    # Print 3000 'x' chars followed by a marker
    script.write_text(
        "print('x' * 3000 + 'MARKER')",
        encoding="utf-8",
    )

    result = run_verification(tmp_path, f"{sys.executable} long.py")

    assert result.ok is True
    assert len(result.stdout_tail) <= 2000
    assert "MARKER" in result.stdout_tail


def test_write_verification_json(tmp_path):
    result = VerificationResult(
        command="python test.py",
        argv=["python", "test.py"],
        ok=True,
        exit_code=0,
        duration_ms=42,
        timed_out=False,
        stdout_tail="ok",
        stderr_tail="",
    )
    out_path = tmp_path / "sub" / "verification.json"

    write_verification_json(result, out_path)

    assert out_path.exists()
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["command"] == "python test.py"
    assert data["argv"] == ["python", "test.py"]
    assert data["ok"] is True
    assert data["exit_code"] == 0
    assert data["duration_ms"] == 42
    assert data["timed_out"] is False
    assert data["stdout_tail"] == "ok"
    assert data["stderr_tail"] == ""


def test_run_verification_stderr_capture(tmp_path):
    script = tmp_path / "err.py"
    script.write_text("import sys; sys.stderr.write('oops\\n'); sys.exit(2)", encoding="utf-8")

    result = run_verification(tmp_path, f"{sys.executable} err.py")

    assert result.ok is False
    assert result.exit_code == 2
    assert "oops" in result.stderr_tail


def test_run_verification_nonexistent_command(tmp_path):
    result = run_verification(tmp_path, "nonexistent_command_xyz_12345")

    assert result.ok is False
    assert result.exit_code != 0
    assert result.timed_out is False
