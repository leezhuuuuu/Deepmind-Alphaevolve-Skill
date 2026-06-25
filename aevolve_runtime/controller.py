"""Run controller for local AlphaEvolve-like experiments."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from dataclasses import dataclass
from dataclasses import replace
import json
from pathlib import Path
import re
import shutil
import time
import uuid

from .evaluator import evaluate_candidate
from .program_db import ProgramDB
from .task_spec import TaskSpec, load_task
from .workspace import materialize_candidate


@dataclass(frozen=True)
class CandidateJobResult:
    candidate_id: str
    patch_path: str | None
    valid: bool
    metrics: dict[str, float]
    feedback: dict
    error: str | None
    touched_files: list[str]


def create_run_id() -> str:
    return f"{time.strftime('run-%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"


def validate_run_id(run_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", run_id):
        raise ValueError("run_id must be a safe basename containing only letters, numbers, dot, underscore, or dash")
    if run_id in {".", ".."}:
        raise ValueError("run_id must not be . or ..")
    return run_id


def run_experiment(task_path: Path, patch_paths: list[Path] | None = None, run_id: str | None = None) -> Path:
    task = load_task(task_path)
    patch_paths = patch_paths or []
    run_id = validate_run_id(run_id or create_run_id())
    runs_root = (task.root / task.runtime.output_dir).resolve()
    _ensure_under(runs_root, task.root.resolve(), "runtime output directory")
    run_dir = (runs_root / run_id).resolve()
    _ensure_under(run_dir, runs_root, "run directory")
    if run_dir.exists() and any(run_dir.iterdir()):
        raise FileExistsError(f"run directory already exists: {run_dir}")
    run_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(task.path, run_dir / "task.yaml")

    db = ProgramDB(run_dir / "run.db")
    db.create_run(run_id, task.path)

    jobs: list[tuple[str, Path | None]] = [("c-000000-baseline", None)]
    patches_dir = run_dir / "patches"
    patches_dir.mkdir(exist_ok=True)
    for index, patch_path in enumerate(patch_paths[: task.budget.candidates], start=1):
        candidate_id = f"c-{index:06d}"
        copied_patch = patches_dir / f"{candidate_id}{patch_path.suffix or '.patch'}"
        shutil.copy2(patch_path, copied_patch)
        jobs.append((candidate_id, copied_patch.resolve()))

    for candidate_id, patch_path in jobs:
        db.insert_candidate(candidate_id, str(patch_path) if patch_path else None)

    _write_status(run_dir, run_id, "running", evaluated=0, queued=len(jobs), best=None, stop_reason=None, db=db, task=task)

    evaluated = 0
    stop_reason = "completed"
    deadline = time.monotonic() + task.budget.max_wall_seconds
    with ThreadPoolExecutor(max_workers=max(1, task.budget.parallelism)) as executor:
        pending_jobs = list(jobs)
        futures = {}
        while pending_jobs or futures:
            while pending_jobs and len(futures) < max(1, task.budget.parallelism):
                if time.monotonic() >= deadline:
                    stop_reason = "wall_time_budget_exhausted"
                    break
                candidate_id, patch_path = pending_jobs.pop(0)
                future = executor.submit(_evaluate_job, task, run_dir, candidate_id, patch_path, deadline)
                futures[future] = candidate_id

            if not futures:
                break

            remaining = max(0.0, deadline - time.monotonic())
            if remaining == 0:
                stop_reason = "wall_time_budget_exhausted"
                break
            done, _pending = wait(futures, timeout=remaining, return_when=FIRST_COMPLETED)
            if not done:
                stop_reason = "wall_time_budget_exhausted"
                break

            for future in done:
                futures.pop(future)
                result = future.result()
                missing_metrics = sorted(task.required_metric_names - set(result.metrics))
                if result.valid and missing_metrics:
                    result = CandidateJobResult(
                        candidate_id=result.candidate_id,
                        patch_path=result.patch_path,
                        valid=False,
                        metrics=result.metrics,
                        feedback=result.feedback,
                        error=f"missing required metrics: {', '.join(missing_metrics)}",
                        touched_files=result.touched_files,
                    )
                db.complete_candidate(
                    candidate_id=result.candidate_id,
                    valid=result.valid,
                    metrics=result.metrics,
                    feedback=result.feedback,
                    error=result.error,
                    touched_files=result.touched_files,
                )
                evaluated += 1
                best = db.best_candidate(task)
                _write_status(
                    run_dir,
                    run_id,
                    "running",
                    evaluated=evaluated,
                    queued=max(0, len(jobs) - evaluated),
                    best=best.candidate_id if best else None,
                    stop_reason=None,
                    db=db,
                    task=task,
                )

        for future, candidate_id in list(futures.items()):
            cancelled = future.cancel()
            db.complete_candidate(
                candidate_id=candidate_id,
                valid=False,
                metrics={},
                feedback={},
                error=(
                    "cancelled because wall-clock budget was exhausted"
                    if cancelled
                    else "did not complete before wall-clock budget was exhausted"
                ),
                touched_files=[],
            )
        for candidate_id, _patch_path in pending_jobs:
            db.complete_candidate(
                candidate_id=candidate_id,
                valid=False,
                metrics={},
                feedback={},
                error="not started because wall-clock budget was exhausted",
                touched_files=[],
            )

    best = db.best_candidate(task)
    db.set_run_state(run_id, "completed", best_candidate=best.candidate_id if best else None, stop_reason=stop_reason)
    _write_status(
        run_dir,
        run_id,
        "completed",
        evaluated=evaluated,
        queued=0,
        best=best.candidate_id if best else None,
        stop_reason=stop_reason,
        db=db,
        task=task,
    )
    _write_report(run_dir, db, task, best.candidate_id if best else None)
    db.close()
    return run_dir


def _evaluate_job(
    task: TaskSpec,
    run_dir: Path,
    candidate_id: str,
    patch_path: Path | None,
    deadline: float,
) -> CandidateJobResult:
    candidate_root = run_dir / "candidates" / candidate_id / "worktree"
    try:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("wall-clock budget exhausted before candidate evaluation started")
        effective_safety = replace(task.safety, timeout_seconds=max(1, min(task.safety.timeout_seconds, int(remaining))))
        touched_files = materialize_candidate(task=task, candidate_dir=candidate_root, patch_path=patch_path)
        result = evaluate_candidate(
            command=task.evaluation.public_command,
            candidate_dir=candidate_root,
            repo_root=task.root,
            evaluation=task.evaluation,
            safety=effective_safety,
        )
        return CandidateJobResult(
            candidate_id=candidate_id,
            patch_path=str(patch_path) if patch_path else None,
            valid=result.valid,
            metrics=result.metrics,
            feedback=result.feedback,
            error=result.error,
            touched_files=touched_files,
        )
    except Exception as exc:
        return CandidateJobResult(
            candidate_id=candidate_id,
            patch_path=str(patch_path) if patch_path else None,
            valid=False,
            metrics={},
            feedback={},
            error=str(exc),
            touched_files=[],
        )


def _write_status(
    run_dir: Path,
    run_id: str,
    state: str,
    *,
    evaluated: int,
    queued: int,
    best: str | None,
    stop_reason: str | None,
    db: ProgramDB,
    task: TaskSpec,
) -> None:
    best_record = db.best_candidate(task)
    status = {
        "run_id": run_id,
        "state": state,
        "evaluated": evaluated,
        "queued": queued,
        "best_candidate": best,
        "best_metrics": best_record.metrics if best_record else {},
        "stop_reason": stop_reason,
    }
    (run_dir / "status.json").write_text(json.dumps(status, indent=2, sort_keys=True), encoding="utf-8")


def _write_report(run_dir: Path, db: ProgramDB, task: TaskSpec, best_candidate: str | None) -> None:
    report_dir = run_dir / "report"
    report_dir.mkdir(parents=True, exist_ok=True)
    candidates = db.list_candidates()
    best_record = next((item for item in candidates if item.candidate_id == best_candidate), None)
    if best_record and best_record.patch_path:
        patch_path = Path(best_record.patch_path)
        if patch_path.exists():
            shutil.copy2(patch_path, report_dir / "champion.patch")

    baseline = next((item for item in candidates if item.candidate_id == "c-000000-baseline"), None)
    lines = [
        "# AlphaEvolve Runtime Report",
        "",
        f"Task: `{task.path}`",
        f"Candidates evaluated: {len(candidates)}",
        f"Best candidate: `{best_candidate or 'none'}`",
        f"Baseline metrics: `{json.dumps(baseline.metrics if baseline else {}, sort_keys=True)}`",
        f"Champion metrics: `{json.dumps(best_record.metrics if best_record else {}, sort_keys=True)}`",
        "",
        "## Candidates",
        "",
        "| Candidate | Valid | Metrics | Error |",
        "| --- | --- | --- | --- |",
    ]
    for item in candidates:
        lines.append(
            f"| `{item.candidate_id}` | {item.valid} | `{json.dumps(item.metrics, sort_keys=True)}` | `{item.error or ''}` |"
        )
    lines.append("")
    lines.append("## Safety Notes")
    lines.append("")
    lines.append(
        "This MVP runtime runs evaluators inside copied candidate work directories with a reduced environment, "
        "but it does not provide container-level network, memory, process, or filesystem isolation."
    )
    (report_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")


def _ensure_under(path: Path, root: Path, label: str) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{label} must stay under {root}: {path}") from exc
