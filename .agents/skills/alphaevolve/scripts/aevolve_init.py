#!/usr/bin/env python3
"""Create a starter .alphaevolve/task.yaml from the bundled template."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from aevolve_common import default_task_path, ensure_alphaevolve_dirs, read_text, repo_root, skill_root, write_text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", default=None, help="TaskSpec path to create")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing task file")
    parser.add_argument("--target-file", default=None, help="Replace the template target file")
    parser.add_argument("--public-command", default=None, help="Replace the template public evaluator command")
    args = parser.parse_args()

    root = repo_root()
    ensure_alphaevolve_dirs(root)
    task_path = Path(args.task).resolve() if args.task else default_task_path(root)
    if task_path.exists() and not args.force:
        print(f"TaskSpec already exists: {task_path}")
        print("Use --force to overwrite it.")
        return 2

    template = read_text(skill_root() / "assets" / "task.example.yaml")
    if args.target_file:
        template = template.replace("src/solver.py", args.target_file)
    if args.public_command:
        template = template.replace(
            "python evaluator/public.py --candidate {candidate_dir}",
            args.public_command,
        )

    write_text(task_path, template)
    print(f"Created TaskSpec: {task_path}")
    print(f"Run directory: {root / '.alphaevolve' / 'runs'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
