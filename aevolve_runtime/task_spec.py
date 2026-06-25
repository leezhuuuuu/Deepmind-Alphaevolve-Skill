"""TaskSpec loading and validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class TaskSpecError(ValueError):
    """Raised when a TaskSpec is missing required structure."""


@dataclass(frozen=True)
class EvolveRegion:
    name: str
    file: str
    marker_start: str | None = None
    marker_end: str | None = None


@dataclass(frozen=True)
class Target:
    files: list[str]
    evolve_regions: list[EvolveRegion] = field(default_factory=list)


@dataclass(frozen=True)
class Objective:
    name: str
    direction: str
    hard_constraint: bool = False
    minimum: float | None = None
    maximum: float | None = None
    weight: float = 1.0


@dataclass(frozen=True)
class Budget:
    candidates: int
    parallelism: int
    max_wall_seconds: int
    stop_after_no_improvement: int | None = None


@dataclass(frozen=True)
class Evaluation:
    public_command: str
    hidden_command: str = ""
    final_command: str = ""
    repetitions: int = 1
    metric_schema_version: int = 1


@dataclass(frozen=True)
class Safety:
    network: bool = False
    source_readonly: bool = True
    candidate_tmpfs: bool = False
    max_memory_mb: int = 512
    timeout_seconds: int = 30
    max_output_bytes: int = 200_000


@dataclass(frozen=True)
class RuntimeConfig:
    output_dir: str = ".alphaevolve/runs"
    database: str = "sqlite"
    patch_mode: str = "search_replace"
    model_adapter: str = "local"


@dataclass(frozen=True)
class TaskSpec:
    path: Path
    root: Path
    target: Target
    objectives: dict[str, Objective]
    budget: Budget
    evaluation: Evaluation
    safety: Safety
    runtime: RuntimeConfig
    raw: dict[str, Any]

    @property
    def primary_objective(self) -> Objective | None:
        soft = [item for item in self.objectives.values() if not item.hard_constraint]
        if soft:
            return soft[0]
        return next(iter(self.objectives.values()), None)

    @property
    def required_metric_names(self) -> set[str]:
        return set(self.objectives)


def repo_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for path in [current, *current.parents]:
        if (path / ".git").exists():
            return path
    return current


def _require_mapping(data: Any, name: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise TaskSpecError(f"{name} must be a mapping")
    return data


def _require_positive_int(data: dict[str, Any], key: str, section: str) -> int:
    value = data.get(key)
    if not isinstance(value, int) or value <= 0:
        raise TaskSpecError(f"{section}.{key} must be a positive integer")
    return value


def load_task(path: str | Path, root: Path | None = None) -> TaskSpec:
    task_path = Path(path).resolve()
    task_root = (root or repo_root(task_path.parent)).resolve()
    with task_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    raw = _require_mapping(raw, "TaskSpec")

    target_data = _require_mapping(raw.get("target"), "target")
    files = target_data.get("files")
    if not isinstance(files, list) or not files or not all(isinstance(item, str) for item in files):
        raise TaskSpecError("target.files must be a non-empty list of strings")
    for file_name in files:
        _validate_relative_path(file_name, "target file")
        if not (task_root / file_name).exists():
            raise TaskSpecError(f"target file does not exist: {file_name}")

    regions: list[EvolveRegion] = []
    for item in target_data.get("evolve_regions") or []:
        item = _require_mapping(item, "target.evolve_regions[]")
        name = item.get("name")
        file_name = item.get("file")
        if not isinstance(name, str) or not isinstance(file_name, str):
            raise TaskSpecError("each evolve region needs string name and file")
        _validate_relative_path(file_name, "evolve region file")
        if file_name not in files:
            raise TaskSpecError(f"evolve region file must be listed in target.files: {file_name}")
        regions.append(
            EvolveRegion(
                name=name,
                file=file_name,
                marker_start=item.get("marker_start"),
                marker_end=item.get("marker_end"),
            )
        )

    objectives_data = _require_mapping(raw.get("objectives"), "objectives")
    objectives: dict[str, Objective] = {}
    for name, item in objectives_data.items():
        item = _require_mapping(item, f"objectives.{name}")
        direction = item.get("direction")
        if direction not in {"maximize", "minimize"}:
            raise TaskSpecError(f"objectives.{name}.direction must be maximize or minimize")
        objectives[name] = Objective(
            name=name,
            direction=direction,
            hard_constraint=bool(item.get("hard_constraint", False)),
            minimum=_maybe_float(item.get("minimum")),
            maximum=_maybe_float(item.get("maximum")),
            weight=float(item.get("weight", 1.0)),
        )
    if not objectives:
        raise TaskSpecError("objectives must not be empty")

    budget_data = _require_mapping(raw.get("budget"), "budget")
    budget = Budget(
        candidates=_require_positive_int(budget_data, "candidates", "budget"),
        parallelism=_require_positive_int(budget_data, "parallelism", "budget"),
        max_wall_seconds=_require_positive_int(budget_data, "max_wall_seconds", "budget"),
        stop_after_no_improvement=_maybe_int(budget_data.get("stop_after_no_improvement")),
    )

    evaluation_data = _require_mapping(raw.get("evaluation"), "evaluation")
    public_command = evaluation_data.get("public_command")
    if not isinstance(public_command, str) or not public_command.strip():
        raise TaskSpecError("evaluation.public_command must be a non-empty string")
    evaluation = Evaluation(
        public_command=public_command,
        hidden_command=str(evaluation_data.get("hidden_command") or ""),
        final_command=str(evaluation_data.get("final_command") or ""),
        repetitions=_positive_int_or_default(evaluation_data.get("repetitions"), 1, "evaluation.repetitions"),
        metric_schema_version=_positive_int_or_default(
            evaluation_data.get("metric_schema_version"), 1, "evaluation.metric_schema_version"
        ),
    )

    safety_data = _require_mapping(raw.get("safety"), "safety")
    safety = Safety(
        network=bool(safety_data.get("network", False)),
        source_readonly=bool(safety_data.get("source_readonly", True)),
        candidate_tmpfs=bool(safety_data.get("candidate_tmpfs", False)),
        max_memory_mb=_positive_int_or_default(safety_data.get("max_memory_mb"), 512, "safety.max_memory_mb"),
        timeout_seconds=_positive_int_or_default(safety_data.get("timeout_seconds"), 30, "safety.timeout_seconds"),
        max_output_bytes=_positive_int_or_default(
            safety_data.get("max_output_bytes"), 200_000, "safety.max_output_bytes"
        ),
    )
    if safety.network:
        raise TaskSpecError("safety.network must be false for this runtime MVP")

    runtime_data = _require_mapping(raw.get("runtime"), "runtime")
    runtime = RuntimeConfig(
        output_dir=str(runtime_data.get("output_dir") or ".alphaevolve/runs"),
        database=str(runtime_data.get("database") or "sqlite"),
        patch_mode=str(runtime_data.get("patch_mode") or "search_replace"),
        model_adapter=str(runtime_data.get("model_adapter") or "local"),
    )
    if runtime.database != "sqlite":
        raise TaskSpecError("runtime.database must be sqlite for this runtime MVP")
    if runtime.patch_mode != "search_replace":
        raise TaskSpecError("runtime.patch_mode must be search_replace for this runtime MVP")
    _validate_relative_path(runtime.output_dir, "runtime.output_dir")
    output_parts = Path(runtime.output_dir).parts
    if not output_parts or output_parts[0] != ".alphaevolve":
        raise TaskSpecError("runtime.output_dir must stay under .alphaevolve for this runtime MVP")

    return TaskSpec(
        path=task_path,
        root=task_root,
        target=Target(files=files, evolve_regions=regions),
        objectives=objectives,
        budget=budget,
        evaluation=evaluation,
        safety=safety,
        runtime=runtime,
        raw=raw,
    )


def _maybe_float(value: Any) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (int, float)):
        raise TaskSpecError(f"expected numeric value, got {value!r}")
    return float(value)


def _maybe_int(value: Any) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or value <= 0:
        raise TaskSpecError(f"expected positive integer, got {value!r}")
    return value


def _positive_int_or_default(value: Any, default: int, name: str) -> int:
    if value is None:
        return default
    if not isinstance(value, int) or value <= 0:
        raise TaskSpecError(f"{name} must be a positive integer")
    return value


def _validate_relative_path(value: str, label: str) -> None:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise TaskSpecError(f"{label} must be a safe relative path: {value}")
