# mico

`mico` is a local coding agent for creating, editing, running, and verifying code inside a workspace.

## Current Status

- Supported tools: `list_files`, `read_file`, `search`, `patch_file` (exact text replacement), `write_file`, `run_command(argv)`.
- `--verify-cmd` for final verification after task completion.
- Fake provider for offline testing; real OpenAI-compatible provider configurable via env or CLI.
- P1 complete: `write_file` and `run_command` implemented.
- Current phase (P2): Real task closure — create code, run verification, fix on failure, pass end-to-end.

## Roadmap

- **P0**: Sync documentation and collaboration rules.
- **P1**: Minimum Working Agent Core (`write_file`, `run_command`).
- **P2**: Real task closure with end-to-end verification.
- **P6**: README polish, demo guide, recorded demos, and safety model.

## Run (fake model, no API key needed)

```bash
python -m mico "list this workspace"
```

After editable install:

```bash
pip install -e .
mico "list this workspace"
```

## Run (OpenAI-compatible provider)

Set your API key and point to an OpenAI-compatible endpoint:

```bash
export MICO_API_KEY="sk-..."
python -m mico --provider openai-compatible --base-url http://localhost:8000/v1 --model gpt-4 "list this workspace"
```

You can also use `--api-key-env` to read from a different environment variable, and `--model-timeout` to adjust the HTTP timeout (default 120s).

For repeated local smoke tests, create or edit a local `.env` file:

```env
MICO_API_KEY=sk-...
MICO_BASE_URL=http://localhost:8000/v1
MICO_MODEL=gpt-4
```

When all three values are present, `python -m mico "list this workspace"` automatically uses the OpenAI-compatible provider. CLI flags still take precedence, and `--provider fake` forces the fake provider. `.env` is ignored by git and should not be committed.

## Tools

Supported tools:

- `list_files` — list directory contents
- `read_file` — read a file by line range
- `search` — search text in workspace
- `patch_file` — exact text replacement in an existing file (requires `--approval auto`)
- `write_file` — write UTF-8 content to a file, creating parent dirs if needed (requires `--approval auto`)
- `run_command` — run a command as argv list with timeout, shell interpreters blocked (requires `--approval auto`)

All paths are sandboxed inside the workspace. `patch_file` requires `old_text` to appear exactly once in the target file. `run_command` accepts a non-empty list of strings, not a shell command string.

## Demo

Try the practical Python task example:

```bash
python -m mico "Create src/fibonacci.py implementing fib(n) with fib(0)=0, fib(1)=1, then run python verify.py to check it passes" --cwd examples/practical-python-task --max-steps 8
```

## Live Smoke (optional, real model)

An optional smoke runner that validates the real OpenAI-compatible provider end-to-end. It includes both read-only and writable (coding task) cases. It is **not** part of the default test suite and requires a working model endpoint.

1. Create or edit local `.env` with `MICO_API_KEY`, `MICO_BASE_URL`, `MICO_MODEL`.
2. Run:

```bash
python -m benchmarks.live
```

The runner creates a temporary workspace, executes four cases (`list_files`, `read_file`, `search`, `create_and_verify_python_task`), and writes a summary to `benchmarks/results/live-latest.json`. The writable case uses `approval_policy=auto` in an isolated temp workspace. No prompts, raw model output, or API keys are recorded in the results.

## Test

```bash
python -m pytest
```
