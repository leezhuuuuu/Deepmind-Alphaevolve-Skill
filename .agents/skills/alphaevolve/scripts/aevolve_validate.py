#!/usr/bin/env python3
"""Validate the structure of an AlphaEvolve TaskSpec."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path

from aevolve_common import default_task_path, read_text, repo_root, shallow_yaml_value


REQUIRED_SECTIONS = ["target", "objectives", "budget", "evaluation", "safety", "runtime"]


def try_load_yaml(path: Path):
    try:
        import yaml  # type: ignore
    except Exception:
        return None
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def validate_text(text: str) -> list[str]:
    errors: list[str] = []
    for section in REQUIRED_SECTIONS:
        if f"{section}:" not in text:
            errors.append(f"missing required section: {section}")
    if "public_command:" not in text:
        errors.append("missing evaluation.public_command")
    if "candidates:" not in text:
        errors.append("missing budget.candidates")
    if "parallelism:" not in text:
        errors.append("missing budget.parallelism")
    if "timeout_seconds:" not in text:
        errors.append("missing safety.timeout_seconds")
    if "network: false" not in text:
        errors.append("safety.network should default to false")
    return errors


def validate_yaml(data) -> list[str]:
    if not isinstance(data, dict):
        return ["task spec is not a YAML object"]
    errors: list[str] = []
    for section in REQUIRED_SECTIONS:
        if section not in data:
            errors.append(f"missing required section: {section}")

    target = data.get("target") or {}
    for file_name in target.get("files") or []:
        if not _is_safe_relative(file_name):
            errors.append(f"target file must be a safe relative path: {file_name}")
            continue
        if not (repo_root() / file_name).exists():
            errors.append(f"target file does not exist: {file_name}")
    for region in target.get("evolve_regions") or []:
        file_name = region.get("file") if isinstance(region, dict) else None
        if file_name and file_name not in (target.get("files") or []):
            errors.append(f"evolve region file must be listed in target.files: {file_name}")

    budget = data.get("budget") or {}
    for key in ["candidates", "parallelism", "max_wall_seconds"]:
        value = budget.get(key)
        if not isinstance(value, int) or value <= 0:
            errors.append(f"budget.{key} must be a positive integer")

    evaluation = data.get("evaluation") or {}
    if not evaluation.get("public_command"):
        errors.append("evaluation.public_command must be set")

    safety = data.get("safety") or {}
    if safety.get("network") is not False:
        errors.append("safety.network must be false unless the user explicitly approves network access")
    for key in ["max_memory_mb", "timeout_seconds", "max_output_bytes"]:
        value = safety.get(key)
        if not isinstance(value, int) or value <= 0:
            errors.append(f"safety.{key} must be a positive integer")
    runtime = data.get("runtime") or {}
    output_dir = runtime.get("output_dir", ".alphaevolve/runs")
    if not isinstance(output_dir, str) or not _is_safe_relative(output_dir):
        errors.append("runtime.output_dir must be a safe relative path")
    elif not Path(output_dir).parts or Path(output_dir).parts[0] != ".alphaevolve":
        errors.append("runtime.output_dir must stay under .alphaevolve")
    return errors


def run_public_command(command: str) -> int:
    argv = [token.replace("{candidate_dir}", str(repo_root())) for token in shlex.split(command)]
    if argv and argv[0] == "python":
        argv[0] = sys.executable
    print(f"Running public evaluator: {' '.join(argv)}")
    completed = subprocess.run(argv, cwd=repo_root(), text=True, capture_output=True)
    if completed.stdout:
        print(completed.stdout.strip())
    if completed.stderr:
        print(completed.stderr.strip(), file=sys.stderr)
    if completed.returncode != 0:
        print(f"Public evaluator exited with {completed.returncode}", file=sys.stderr)
        return completed.returncode
    try:
        parsed = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        print(f"Public evaluator did not emit JSON: {exc}", file=sys.stderr)
        return 1
    if not isinstance(parsed, dict) or "valid" not in parsed or "metrics" not in parsed:
        print("Public evaluator JSON must contain valid and metrics fields", file=sys.stderr)
        return 1
    return 0


def _is_safe_relative(value: str) -> bool:
    path = Path(value)
    return not path.is_absolute() and ".." not in path.parts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", default=None, help="TaskSpec path")
    parser.add_argument("--run-public", action="store_true", help="Run the public evaluator against the repository baseline")
    args = parser.parse_args()

    task_path = Path(args.task).resolve() if args.task else default_task_path()
    if not task_path.exists():
        print(f"TaskSpec not found: {task_path}", file=sys.stderr)
        print("Run aevolve_init.py first.", file=sys.stderr)
        return 2

    text = read_text(task_path)
    errors = validate_text(text)
    yaml_data = try_load_yaml(task_path)
    if yaml_data is not None:
        errors.extend(validate_yaml(yaml_data))

    if errors:
        print("TaskSpec validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print(f"TaskSpec validation passed: {task_path}")

    if args.run_public:
        public_command = None
        if isinstance(yaml_data, dict):
            public_command = (yaml_data.get("evaluation") or {}).get("public_command")
        public_command = public_command or shallow_yaml_value(text, "public_command")
        if not public_command:
            print("No public_command found.", file=sys.stderr)
            return 1
        return run_public_command(public_command)
    return 0


if __name__ == "__main__":
    sys.exit(main())
