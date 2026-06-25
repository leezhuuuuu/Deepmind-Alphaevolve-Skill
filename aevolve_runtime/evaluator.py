"""Evaluator command execution and metric aggregation."""

from __future__ import annotations

from dataclasses import dataclass
import json
import shlex
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .task_spec import Evaluation, Safety


@dataclass(frozen=True)
class EvaluationResult:
    valid: bool
    metrics: dict[str, float]
    feedback: dict[str, Any]
    command: str
    repetitions: int
    raw_results: list[dict[str, Any]]
    error: str | None = None


def evaluate_candidate(
    *,
    command: str,
    candidate_dir: Path,
    repo_root: Path,
    evaluation: Evaluation,
    safety: Safety,
) -> EvaluationResult:
    """Run an evaluator command repeatedly and aggregate numeric metrics."""

    rendered = command.replace("{candidate_dir}", str(candidate_dir))
    raw_results: list[dict[str, Any]] = []
    errors: list[str] = []
    for _ in range(evaluation.repetitions):
        result, error = _run_once(rendered, repo_root, safety)
        if error:
            errors.append(error)
        if result is not None:
            raw_results.append(result)

    if errors:
        return EvaluationResult(
            valid=False,
            metrics={},
            feedback={"errors": errors},
            command=rendered,
            repetitions=evaluation.repetitions,
            raw_results=raw_results,
            error="; ".join(errors),
        )

    valid = all(bool(item.get("valid")) for item in raw_results)
    metrics = _aggregate_metrics(raw_results)
    feedback = {"runs": [item.get("feedback", {}) for item in raw_results]}
    return EvaluationResult(
        valid=valid,
        metrics=metrics,
        feedback=feedback,
        command=rendered,
        repetitions=evaluation.repetitions,
        raw_results=raw_results,
        error=None,
    )


def _run_once(command: str, cwd: Path, safety: Safety) -> tuple[dict[str, Any] | None, str | None]:
    started = time.perf_counter()
    try:
        argv = shlex.split(command)
        if argv and argv[0] == "python":
            argv[0] = sys.executable
        completed = subprocess.run(
            argv,
            cwd=cwd,
            text=True,
            capture_output=True,
            timeout=safety.timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return None, f"evaluator timed out after {safety.timeout_seconds}s"

    stdout = completed.stdout[-safety.max_output_bytes :]
    stderr = completed.stderr[-safety.max_output_bytes :]
    if completed.returncode != 0:
        return None, f"evaluator exited {completed.returncode}: {stderr.strip()}"
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError as exc:
        return None, f"evaluator did not emit JSON: {exc}"
    if not isinstance(parsed, dict):
        return None, "evaluator JSON must be an object"
    if "valid" not in parsed or "metrics" not in parsed:
        return None, "evaluator JSON must contain valid and metrics"
    metrics = parsed.get("metrics")
    if not isinstance(metrics, dict):
        return None, "metrics must be an object"
    for key, value in metrics.items():
        if not isinstance(value, (int, float)):
            return None, f"metric {key} must be numeric"
    parsed.setdefault("feedback", {})
    parsed.setdefault("timing", {})
    parsed["timing"]["runtime_seconds_observed"] = time.perf_counter() - started
    return parsed, None


def _aggregate_metrics(results: list[dict[str, Any]]) -> dict[str, float]:
    values: dict[str, list[float]] = {}
    for result in results:
        for key, value in result.get("metrics", {}).items():
            values.setdefault(key, []).append(float(value))
    return {key: float(statistics.median(items)) for key, items in values.items() if items}
