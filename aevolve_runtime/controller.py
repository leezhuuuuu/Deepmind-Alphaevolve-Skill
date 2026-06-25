"""Run controller for local AlphaEvolve-like experiments."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import time

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
    return time.strftime("run-%Y%m%d-%H%M%S")


def run_experiment(task_path: Path, patch_paths: list[Path] | None = None, run_id: str | None = None) -> Path:
    task = load_task(task_path)
    patch_paths = patch_paths or []
    run_id = run_id or create_run_id()
    run_dir = (task.root / task.runtime.output_dir / run_id).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(task.path, run_dir / "task.yaml")

    db = ProgramDB(run_dir / "run.db")
    db.create_run(run_id, task.path)

    jobs: list[tuple[str, Path | None]] = [("c-000000-baseline", None)]
    for index, patch_path in enumerate(patch_paths[: task.budget.candidates], start=1):
        jobs.append((f"c-{index:06d}", patch_path.resolve()))

    for candidate_id, patch_path in jobs:
        db.insert_candidate(candidate_id, str(patch_path) if patch_path else None)

    _write_status(run_dir, run_id, "running", evaluated=0, queued=len(jobs), best=None, stop_reason=None, db=db, task=task)

    evaluated = 0
    stop_reason = "completed"
    with ThreadPoolExecutor(max_workers=max(1, task.budget.parallelism)) as executor:
        futures = {
            executor.submit(_evaluate_job, task, run_dir, candidate_id, patch_path): (candidate_id, patch_path)
            for candidate_id, patch_path in jobs
        }
        for future in as_completed(futures):
            result = future.result()
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


def _evaluate_job(task: TaskSpec, run_dir: Path, candidate_id: str, patch_path: Path | None) -> CandidateJobResult:
    candidate_root = run_dir / "candidates" / candidate_id / "worktree"
    try:
        touched_files = materialize_candidate(task=task, candidate_dir=candidate_root, patch_path=patch_path)
        result = evaluate_candidate(
            command=task.evaluation.public_command,
            candidate_dir=candidate_root,
            repo_root=task.root,
            evaluation=task.evaluation,
            safety=task.safety,
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
    lines = [
        "# AlphaEvolve Runtime Report",
        "",
        f"Task: `{task.path}`",
        f"Candidates evaluated: {len(candidates)}",
        f"Best candidate: `{best_candidate or 'none'}`",
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
    lines.append("This MVP runtime copies candidates into isolated work directories, but does not provide container-level isolation.")
    (report_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")
