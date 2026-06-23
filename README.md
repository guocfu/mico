# mico

`mico` is a tiny local coding agent demo. By default it runs without model keys or network access:

1. A CLI receives a user prompt.
2. A model asks to call a workspace tool.
3. The agent executes the tool inside the workspace.
4. The fake model returns a final answer.
5. Run traces are saved under `.mico/runs/`.

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

For repeated local smoke tests, copy `.env.example` to `.env` and fill in:

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

1. Copy `.env.example` to `.env` and fill in `MICO_API_KEY`, `MICO_BASE_URL`, `MICO_MODEL`.
2. Run:

```bash
python -m benchmarks.live
```

The runner creates a temporary workspace, executes three read-only cases (`list_files`, `read_file`, `search`), and writes a summary to `benchmarks/results/live-latest.json`. No prompts, raw model output, or API keys are recorded in the results.

## Test

```bash
python -m pytest
```
