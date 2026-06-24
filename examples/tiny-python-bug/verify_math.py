import sys

sys.path.insert(0, ".")
from math_buggy import add

assert add(1, 2) == 3, f"add(1, 2) expected 3, got {add(1, 2)}"
assert add(-1, 1) == 0, f"add(-1, 1) expected 0, got {add(-1, 1)}"
assert add(0, 0) == 0, f"add(0, 0) expected 0, got {add(0, 0)}"
print("ALL TESTS PASSED")
