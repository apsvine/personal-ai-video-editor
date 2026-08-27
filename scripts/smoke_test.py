"""Run the foundation health test with the Python standard library."""

from pathlib import Path
import sys
import unittest


def main():
    root = Path(__file__).resolve().parents[1]
    suite = unittest.defaultTestLoader.discover(str(root / "tests" / "unit"))
    if suite.countTestCases() == 0:
        print("FAIL: no health tests discovered", file=sys.stderr)
        return 1
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
