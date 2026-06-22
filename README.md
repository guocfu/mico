# mico

`mico` is a tiny local coding agent demo. The first version runs without model keys or network access:

1. A CLI receives a user prompt.
2. A fake model asks to call a read-only tool.
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

## Tools

Currently only read-only tools are supported: `list_files`, `read_file`, `search`. All paths are sandboxed inside the workspace.

## Test

```bash
python -m pytest
```
