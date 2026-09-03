"""
Run every test suite. No dependencies, no Houdini -- hou and PySide are
stubbed, so this runs anywhere Python does.

    python tests/run_all.py
"""
import glob
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    suites = sorted(
        os.path.basename(f) for f in glob.glob(os.path.join(HERE, "test_*.py"))
    )
    failed = []

    for suite in suites:
        result = subprocess.run(
            [sys.executable, os.path.join(HERE, suite)],
            capture_output=True, text=True)
        tail = (result.stdout.strip().splitlines() or ["no output"])[-1]
        status = "PASS" if result.returncode == 0 else "FAIL"
        print("{:<20} {:<6} {}".format(suite, status, tail))
        if result.returncode != 0:
            failed.append(suite)
            if result.stderr.strip():
                print(result.stderr.strip())

    print()
    if failed:
        print("{} suite(s) failed: {}".format(len(failed), ", ".join(failed)))
        return 1
    print("All {} suites passed.".format(len(suites)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
