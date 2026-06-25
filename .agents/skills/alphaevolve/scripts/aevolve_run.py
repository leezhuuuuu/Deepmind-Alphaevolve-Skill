#!/usr/bin/env python3
"""Delegate an AlphaEvolve run to an installed aevolve_runtime package."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from aevolve_common import default_task_path, repo_root


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", default=None, help="TaskSpec path")
    args, runtime_args = parser.parse_known_args()

    task_path = Path(args.task).resolve() if args.task else default_task_path()
    if not task_path.exists():
        print(f"TaskSpec not found: {task_path}", file=sys.stderr)
        return 2

    command = [sys.executable, "-m", "aevolve_runtime.cli", "run", "--task", str(task_path), *runtime_args]
    print("Delegating to runtime:")
    print(" ".join(command))
    completed = subprocess.run(command, cwd=repo_root())
    if completed.returncode != 0:
        print(
            "Runtime command failed. If aevolve_runtime is not implemented yet, scaffold it as a separate runtime package.",
            file=sys.stderr,
        )
    return completed.returncode


if __name__ == "__main__":
    sys.exit(main())
