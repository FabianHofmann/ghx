#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

import subprocess
import sys


def main() -> int:
    result = subprocess.run(
        ["gh", "pr", "view", "--json", "number", "-q", ".number"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print("No PR found for current branch", file=sys.stderr)
        return 1

    pr_number = result.stdout.strip()
    subprocess.run(["gh", "pr", "view", pr_number, "--web"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
