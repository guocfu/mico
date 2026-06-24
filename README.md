# mico

`mico` is a local coding agent for creating, editing, running, and verifying code inside a workspace.

## Current Status

- Supported tools: `list_files`, `read_file`, `search`, `patch_file` (exact text replacement).
- `--verify-cmd` for final verification after task completion.
- Fake provider for offline testing; real OpenAI-compatible provider configurable via env or CLI.
- Next phase (P1): `write_file` and `run_command(argv)` to complete real code task loops.

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

All paths are sandboxed inside the workspace. `patch_file` requires `old_text` to appear exactly once in the target file.

## Live Smoke (optional, real model)

An optional smoke runner that validates the real OpenAI-compatible provider end-to-end with read-only tools. It is **not** part of the default test suite and requires a working model endpoint.

1. Create or edit local `.env` with `MICO_API_KEY`, `MICO_BASE_URL`, `MICO_MODEL`.
2. Run:

```bash
python -m benchmarks.live
```

The runner creates a temporary workspace, executes three read-only cases (`list_files`, `read_file`, `search`), and writes a summary to `benchmarks/results/live-latest.json`. No prompts, raw model output, or API keys are recorded in the results.

## Test

```bash
python -m pytest
```
