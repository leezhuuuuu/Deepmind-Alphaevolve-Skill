"""Candidate workspace materialization."""

from __future__ import annotations

import shutil
from pathlib import Path

from .patch_engine import load_and_apply_patch
from .task_spec import TaskSpec


IGNORE_NAMES = {".git", ".alphaevolve", "__pycache__", ".pytest_cache", ".mypy_cache"}


def copy_repo_to_candidate(source_root: Path, candidate_dir: Path) -> None:
    if candidate_dir.exists():
        shutil.rmtree(candidate_dir)
    shutil.copytree(source_root, candidate_dir, ignore=_ignore)


def materialize_candidate(
    *,
    task: TaskSpec,
    candidate_dir: Path,
    patch_path: Path | None,
) -> list[str]:
    copy_repo_to_candidate(task.root, candidate_dir)
    if patch_path is None:
        return []
    default_file = task.target.files[0] if len(task.target.files) == 1 else None
    allowed_files = {Path(file_name).as_posix() for file_name in task.target.files}
    return load_and_apply_patch(candidate_dir, patch_path, default_file=default_file, allowed_files=allowed_files)


def _ignore(_dir: str, names: list[str]) -> set[str]:
    return {name for name in names if name in IGNORE_NAMES or name.endswith(".pyc")}
