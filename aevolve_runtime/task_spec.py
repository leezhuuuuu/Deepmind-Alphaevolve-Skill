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
class GenerationApiConfig:
    provider: str = "deepseek"
    base_url: str = "https://api.deepseek.com"
    api_key_env: str = "DEEPSEEK_API_KEY"
    model: str = "deepseek-v4-flash"
    temperature: float = 0.7
    max_tokens: int = 4096
    timeout_seconds: int = 90
    thinking: str = "disabled"
    reasoning_effort: str | None = None


@dataclass(frozen=True)
class GenerationAgentConfig:
    backend: str = "codex"
    prompt_dir: str = ".alphaevolve/agent-prompts"
    max_agents: int = 2


@dataclass(frozen=True)
class GenerationConfig:
    mode: str = "patch_dir"
    batch_size: int = 1
    max_prompt_chars: int = 60_000
    api: GenerationApiConfig = field(default_factory=GenerationApiConfig)
    agent: GenerationAgentConfig = field(default_factory=GenerationAgentConfig)


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
    generation: GenerationConfig
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

    generation = _parse_generation(raw.get("generation"))

    return TaskSpec(
        path=task_path,
        root=task_root,
        target=Target(files=files, evolve_regions=regions),
        objectives=objectives,
        budget=budget,
        evaluation=evaluation,
        safety=safety,
        runtime=runtime,
        generation=generation,
        raw=raw,
    )


def _parse_generation(data: Any) -> GenerationConfig:
    if data is None:
        return GenerationConfig()
    generation_data = _require_mapping(data, "generation")
    mode = str(generation_data.get("mode") or "patch_dir")
    if mode not in {"patch_dir", "api", "agent", "hybrid"}:
        raise TaskSpecError("generation.mode must be patch_dir, api, agent, or hybrid")

    api_data = generation_data.get("api") or {}
    api_data = _require_mapping(api_data, "generation.api")
    provider = str(api_data.get("provider") or "deepseek")
    base_url = str(api_data.get("base_url") or "https://api.deepseek.com").rstrip("/")
    api_key_env = str(api_data.get("api_key_env") or "DEEPSEEK_API_KEY")
    model = str(api_data.get("model") or "deepseek-v4-flash")
    thinking = str(api_data.get("thinking") or "disabled")
    reasoning_effort = api_data.get("reasoning_effort")
    if reasoning_effort is not None:
        reasoning_effort = str(reasoning_effort)
    if not provider.strip():
        raise TaskSpecError("generation.api.provider must be non-empty")
    if not base_url.startswith(("http://", "https://")):
        raise TaskSpecError("generation.api.base_url must be an HTTP(S) URL")
    if not api_key_env.strip():
        raise TaskSpecError("generation.api.api_key_env must be non-empty")
    if not model.strip():
        raise TaskSpecError("generation.api.model must be non-empty")
    if thinking not in {"enabled", "disabled"}:
        raise TaskSpecError("generation.api.thinking must be enabled or disabled")

    agent_data = generation_data.get("agent") or {}
    agent_data = _require_mapping(agent_data, "generation.agent")
    backend = str(agent_data.get("backend") or "codex")
    prompt_dir = str(agent_data.get("prompt_dir") or ".alphaevolve/agent-prompts")
    if backend not in {"codex", "claude-code", "manual"}:
        raise TaskSpecError("generation.agent.backend must be codex, claude-code, or manual")
    _validate_relative_path(prompt_dir, "generation.agent.prompt_dir")
    prompt_parts = Path(prompt_dir).parts
    if not prompt_parts or prompt_parts[0] != ".alphaevolve":
        raise TaskSpecError("generation.agent.prompt_dir must stay under .alphaevolve")

    return GenerationConfig(
        mode=mode,
        batch_size=_positive_int_or_default(generation_data.get("batch_size"), 1, "generation.batch_size"),
        max_prompt_chars=_positive_int_or_default(
            generation_data.get("max_prompt_chars"), 60_000, "generation.max_prompt_chars"
        ),
        api=GenerationApiConfig(
            provider=provider,
            base_url=base_url,
            api_key_env=api_key_env,
            model=model,
            temperature=_float_or_default(api_data.get("temperature"), 0.7, "generation.api.temperature"),
            max_tokens=_positive_int_or_default(api_data.get("max_tokens"), 4096, "generation.api.max_tokens"),
            timeout_seconds=_positive_int_or_default(
                api_data.get("timeout_seconds"), 90, "generation.api.timeout_seconds"
            ),
            thinking=thinking,
            reasoning_effort=reasoning_effort,
        ),
        agent=GenerationAgentConfig(
            backend=backend,
            prompt_dir=prompt_dir,
            max_agents=_positive_int_or_default(agent_data.get("max_agents"), 2, "generation.agent.max_agents"),
        ),
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


def _float_or_default(value: Any, default: float, name: str) -> float:
    if value is None:
        return default
    if not isinstance(value, (int, float)):
        raise TaskSpecError(f"{name} must be numeric")
    result = float(value)
    if result < 0:
        raise TaskSpecError(f"{name} must be non-negative")
    return result


def _validate_relative_path(value: str, label: str) -> None:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise TaskSpecError(f"{label} must be a safe relative path: {value}")
