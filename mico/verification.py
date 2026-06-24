import json
import shlex
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class VerificationResult:
    command: str
    argv: list
    ok: bool
    exit_code: int
    duration_ms: int
    timed_out: bool
    stdout_tail: str
    stderr_tail: str


def run_verification(workspace_root, verify_cmd, timeout=120):
    if isinstance(verify_cmd, str):
        # On Windows, posix=False preserves backslashes in paths (e.g. C:\Users\...).
        # On POSIX, default posix=True handles backslash escaping correctly.
        posix_mode = sys.platform != "win32"
        argv = shlex.split(verify_cmd, posix=posix_mode)
    else:
        argv = list(verify_cmd)
    if not argv:
        raise ValueError("verify_cmd must not be empty")
    started = time.monotonic()
    try:
        proc = subprocess.run(
            argv,
            cwd=str(workspace_root),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        duration_ms = int((time.monotonic() - started) * 1000)
        return VerificationResult(
            command=verify_cmd if isinstance(verify_cmd, str) else " ".join(verify_cmd),
            argv=argv,
            ok=(proc.returncode == 0),
            exit_code=proc.returncode,
            duration_ms=duration_ms,
            timed_out=False,
            stdout_tail=proc.stdout[-2000:] if proc.stdout else "",
            stderr_tail=proc.stderr[-2000:] if proc.stderr else "",
        )
    except (FileNotFoundError, OSError) as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        return VerificationResult(
            command=verify_cmd if isinstance(verify_cmd, str) else " ".join(verify_cmd),
            argv=argv,
            ok=False,
            exit_code=-1,
            duration_ms=duration_ms,
            timed_out=False,
            stdout_tail="",
            stderr_tail=str(exc),
        )
    except subprocess.TimeoutExpired as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        return VerificationResult(
            command=verify_cmd if isinstance(verify_cmd, str) else " ".join(verify_cmd),
            argv=argv,
            ok=False,
            exit_code=-1,
            duration_ms=duration_ms,
            timed_out=True,
            stdout_tail=stdout[-2000:],
            stderr_tail=stderr[-2000:],
        )


def write_verification_json(result, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(asdict(result), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path
