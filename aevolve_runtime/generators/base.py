"""Shared generator contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import json
from pathlib import Path

from aevolve_runtime.task_spec import TaskSpec


@dataclass(frozen=True)
class GeneratedPatch:
    patch_text: str
    source: str
    metadata: dict[str, str] = field(default_factory=dict)


class PatchGenerator(ABC):
    @abstractmethod
    def generate(self, task: TaskSpec, *, count: int) -> list[GeneratedPatch]:
        """Generate candidate SEARCH/REPLACE patches."""


def write_generated_patches(
    patches: list[GeneratedPatch],
    output_dir: Path,
    *,
    prefix: str = "generated",
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    patch_paths: list[Path] = []
    manifest = []
    for index, patch in enumerate(patches, start=1):
        path = output_dir / f"{prefix}-{index:06d}.patch"
        path.write_text(_normalize_patch_text(patch.patch_text), encoding="utf-8")
        patch_paths.append(path)
        manifest.append(
            {
                "path": str(path),
                "source": patch.source,
                "metadata": patch.metadata,
            }
        )
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return patch_paths


def _normalize_patch_text(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    return f"{value}\n"
