"""Command-line interface for the local AlphaEvolve-like runtime."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from .controller import run_experiment
from .program_db import ProgramDB
from .task_spec import TaskSpecError, load_task, repo_root


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aevolve", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate", help="Validate a TaskSpec")
    validate_parser.add_argument("--task", required=True)

    run_parser = subparsers.add_parser("run", help="Run a local experiment")
    run_parser.add_argument("--task", required=True)
    run_parser.add_argument("--patch", action="append", default=[], help="Candidate SEARCH/REPLACE patch file")
    run_parser.add_argument("--patch-dir", default=None, help="Directory of .patch/.diff/.txt candidate patches")
    run_parser.add_argument("--run-id", default=None)

    status_parser = subparsers.add_parser("status", help="Print run status")
    status_parser.add_argument("--run-dir", default=None)
    status_parser.add_argument("--json", action="store_true")

    review_parser = subparsers.add_parser("review", help="Print run report excerpt")
    review_parser.add_argument("--run-dir", default=None)

    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            task = load_task(args.task)
            print(f"TaskSpec valid: {task.path}")
            return 0
        if args.command == "run":
            patch_paths = [Path(item) for item in args.patch]
            if args.patch_dir:
                patch_paths.extend(_patches_from_dir(Path(args.patch_dir)))
            run_dir = run_experiment(Path(args.task), patch_paths=patch_paths, run_id=args.run_id)
            print(f"Run complete: {run_dir}")
            print((run_dir / "status.json").read_text(encoding="utf-8"))
            return 0
        if args.command == "status":
            return _status(args.run_dir, args.json)
        if args.command == "review":
            return _review(args.run_dir)
    except TaskSpecError as exc:
        print(f"TaskSpec error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Runtime error: {exc}", file=sys.stderr)
        return 1
    return 2


def _patches_from_dir(path: Path) -> list[Path]:
    if not path.exists():
        raise FileNotFoundError(path)
    return sorted(
        item
        for item in path.iterdir()
        if item.is_file() and item.suffix.lower() in {".patch", ".diff", ".txt"}
    )


def _latest_run_dir() -> Path | None:
    runs_root = repo_root() / ".alphaevolve" / "runs"
    if not runs_root.exists():
        return None
    dirs = [item for item in runs_root.iterdir() if item.is_dir()]
    if not dirs:
        return None
    return max(dirs, key=lambda item: item.stat().st_mtime)


def _resolve_run_dir(run_dir: str | None) -> Path:
    if run_dir:
        return Path(run_dir).resolve()
    latest = _latest_run_dir()
    if latest is None:
        raise FileNotFoundError("no run directories found")
    return latest


def _status(run_dir_arg: str | None, raw_json: bool) -> int:
    run_dir = _resolve_run_dir(run_dir_arg)
    status_path = run_dir / "status.json"
    if not status_path.exists():
        print(f"Missing status file: {status_path}", file=sys.stderr)
        return 2
    status = json.loads(status_path.read_text(encoding="utf-8"))
    if raw_json:
        print(json.dumps(status, indent=2, sort_keys=True))
        return 0
    print(f"Run: {status.get('run_id', run_dir.name)}")
    print(f"State: {status.get('state')}")
    print(f"Evaluated: {status.get('evaluated')}")
    print(f"Queued: {status.get('queued')}")
    print(f"Best candidate: {status.get('best_candidate')}")
    print(f"Best metrics: {json.dumps(status.get('best_metrics') or {}, sort_keys=True)}")
    if status.get("stop_reason"):
        print(f"Stop reason: {status['stop_reason']}")
    return 0


def _review(run_dir_arg: str | None) -> int:
    run_dir = _resolve_run_dir(run_dir_arg)
    report_path = run_dir / "report" / "report.md"
    status_path = run_dir / "status.json"
    if status_path.exists():
        print(status_path.read_text(encoding="utf-8"))
    if report_path.exists():
        print("\n" + report_path.read_text(encoding="utf-8"))
        return 0
    db_path = run_dir / "run.db"
    if db_path.exists():
        _print_db_summary(db_path)
        return 0
    print(f"No report artifacts found in {run_dir}", file=sys.stderr)
    return 2


def _print_db_summary(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT candidate_id, valid, metrics, error FROM candidates ORDER BY candidate_id").fetchall()
    print("Candidates:")
    for row in rows:
        print(f"- {row['candidate_id']}: valid={bool(row['valid'])} metrics={row['metrics']} error={row['error'] or ''}")
    conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
