# practical-python-task

Minimal coding agent task: create a Fibonacci implementation and verify it passes.

## Task

Create `src/fibonacci.py` implementing `fib(n)` with:
- `fib(0) = 0`
- `fib(1) = 1`
- `fib(n) = fib(n-1) + fib(n-2)` for `n >= 2`

Then run `python verify.py` to confirm correctness.

## Usage

From the repository root:

```bash
# Run agent to create fibonacci.py and verify it
python -m mico "Create src/fibonacci.py implementing fib(n) with fib(0)=0, fib(1)=1, then run python verify.py to check it passes" --cwd examples/practical-python-task --max-steps 8
```
