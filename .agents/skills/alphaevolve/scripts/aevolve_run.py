#!/usr/bin/env python3
"""Delegate an AlphaEvolve run to an installed aevolve_runtime package."""

from __future__ import annotations

import argparse
import os
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

    runtime_root = find_runtime_root()
    command = [sys.executable, "-m", "aevolve_runtime.cli", "run", "--task", str(task_path), *runtime_args]
    env = os.environ.copy()
    if runtime_root:
        existing = env.get("PYTHONPATH")
        env["PYTHONPATH"] = str(runtime_root) if not existing else f"{runtime_root}{os.pathsep}{existing}"
    print("Delegating to runtime:", flush=True)
    print(" ".join(command), flush=True)
    completed = subprocess.run(command, cwd=repo_root(), env=env)
    if completed.returncode != 0:
        print(
            "Runtime command failed. Install aevolve_runtime or run this helper from a checkout that contains it.",
            file=sys.stderr,
        )
    return completed.returncode


def find_runtime_root() -> Path | None:
    for path in Path(__file__).resolve().parents:
        if (path / "aevolve_runtime").is_dir():
            return path
    return None


if __name__ == "__main__":
    sys.exit(main())
