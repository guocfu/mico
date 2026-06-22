# mico

`mico` is a tiny local coding agent demo. The first version runs without model keys or network access:

1. A CLI receives a user prompt.
2. A fake model asks to call a read-only tool.
3. The agent executes the tool inside the workspace.
4. The fake model returns a final answer.
5. Run traces are saved under `.mico/runs/`.

## Run

```bash
python -m mico "list this workspace"
```

After editable install:

```bash
pip install -e .
mico "list this workspace"
```

## Test

```bash
python -m pytest
```
