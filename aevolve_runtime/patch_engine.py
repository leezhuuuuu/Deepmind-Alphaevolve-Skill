"""SEARCH/REPLACE patch parsing and application."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class PatchError(ValueError):
    """Raised when a candidate patch cannot be parsed or applied."""


@dataclass(frozen=True)
class Replacement:
    file: str
    search: str
    replace: str


def parse_patch(text: str, default_file: str | None = None) -> list[Replacement]:
    """Parse SEARCH/REPLACE blocks.

    Supported file markers before a block:
    - `FILE: path`
    - `### FILE: path`
    - `*** File: path`

    If no marker is present, `default_file` is used.
    """

    lines = text.replace("\r\n", "\n").splitlines(keepends=True)
    current_file = default_file
    replacements: list[Replacement] = []
    i = 0
    while i < len(lines):
        marker_file = _file_marker(lines[i])
        if marker_file:
            current_file = marker_file
            i += 1
            continue
        if lines[i].strip() != "<<<<<<< SEARCH":
            i += 1
            continue

        file_name = current_file
        if not file_name:
            raise PatchError("SEARCH/REPLACE block has no file marker and no default file")
        i += 1
        search_lines: list[str] = []
        while i < len(lines) and lines[i].strip() != "=======":
            search_lines.append(lines[i])
            i += 1
        if i >= len(lines):
            raise PatchError("missing ======= separator")
        i += 1
        replace_lines: list[str] = []
        while i < len(lines) and lines[i].strip() != ">>>>>>> REPLACE":
            replace_lines.append(lines[i])
            i += 1
        if i >= len(lines):
            raise PatchError("missing >>>>>>> REPLACE terminator")
        i += 1
        search = "".join(search_lines)
        replace = "".join(replace_lines)
        if not search:
            raise PatchError("SEARCH block must not be empty")
        replacements.append(Replacement(file=file_name, search=search, replace=replace))

    if not replacements:
        raise PatchError("patch did not contain any SEARCH/REPLACE blocks")
    return replacements


def apply_replacements(root: Path, replacements: list[Replacement]) -> list[str]:
    """Apply replacements under `root` and return touched relative paths."""

    touched: list[str] = []
    for replacement in replacements:
        rel_path = Path(replacement.file)
        if rel_path.is_absolute() or ".." in rel_path.parts:
            raise PatchError(f"unsafe patch path: {replacement.file}")
        path = root / rel_path
        if not path.exists():
            raise PatchError(f"patch target does not exist: {replacement.file}")
        content = path.read_text(encoding="utf-8")
        count = content.count(replacement.search)
        if count != 1:
            raise PatchError(f"SEARCH block matched {count} times in {replacement.file}; expected exactly 1")
        path.write_text(content.replace(replacement.search, replacement.replace, 1), encoding="utf-8")
        if replacement.file not in touched:
            touched.append(replacement.file)
    return touched


def load_and_apply_patch(root: Path, patch_path: Path, default_file: str | None = None) -> list[str]:
    patch_text = patch_path.read_text(encoding="utf-8")
    replacements = parse_patch(patch_text, default_file=default_file)
    return apply_replacements(root, replacements)


def _file_marker(line: str) -> str | None:
    stripped = line.strip()
    prefixes = ["FILE:", "### FILE:", "*** File:"]
    for prefix in prefixes:
        if stripped.startswith(prefix):
            value = stripped[len(prefix) :].strip()
            return value or None
    return None
