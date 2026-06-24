"""Verification script for fibonacci.py — no external dependencies."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from fibonacci import fib

EXPECTED = {
    0: 0,
    1: 1,
    2: 1,
    3: 2,
    5: 5,
    10: 55,
    20: 6765,
}

for n, expected in EXPECTED.items():
    result = fib(n)
    assert result == expected, f"fib({n}) = {result}, expected {expected}"

print("ALL TESTS PASSED")
