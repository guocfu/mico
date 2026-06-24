# tiny-python-bug

Minimal example for mico verified coding agent demo.

## Bug

`math_buggy.py` has `add(a, b)` returning `a - b` instead of `a + b`.

## Usage

From the repository root:

```bash
# Run agent to fix the bug, then verify
python -m mico "Fix the bug in math_buggy.py so add() returns the correct sum" --cwd examples/tiny-python-bug --verify-cmd "python verify_math.py"

# Without verification
python -m mico "Fix the bug in math_buggy.py" --cwd examples/tiny-python-bug
```
