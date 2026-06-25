#!/usr/bin/env python3
"""Shared helpers for the alphaevolve skill scripts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def repo_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for path in [current, *current.parents]:
        if (path / ".git").exists():
            return path
    return current


def skill_root() -> Path:
    return Path(__file__).resolve().parents[1]


def default_task_path(root: Path | None = None) -> Path:
    return (root or repo_root()) / ".alphaevolve" / "task.yaml"


def ensure_alphaevolve_dirs(root: Path | None = None) -> Path:
    base = (root or repo_root()) / ".alphaevolve"
    for child in [base, base / "runs"]:
        child.mkdir(parents=True, exist_ok=True)
    return base


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} does not contain a JSON object")
    return data


def latest_run_dir(root: Path | None = None) -> Path | None:
    runs_dir = (root or repo_root()) / ".alphaevolve" / "runs"
    if not runs_dir.exists():
        return None
    dirs = [path for path in runs_dir.iterdir() if path.is_dir()]
    if not dirs:
        return None
    return max(dirs, key=lambda path: path.stat().st_mtime)


def shallow_yaml_value(text: str, key: str) -> str | None:
    prefix = f"{key}:"
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith(prefix):
            return line[len(prefix) :].strip().strip('"').strip("'")
    return None
