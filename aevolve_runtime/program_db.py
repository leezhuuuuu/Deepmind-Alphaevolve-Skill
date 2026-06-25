"""SQLite-backed run and candidate archive."""

from __future__ import annotations

from dataclasses import dataclass
import json
import sqlite3
from pathlib import Path
from typing import Any

from .task_spec import TaskSpec


@dataclass(frozen=True)
class CandidateRecord:
    candidate_id: str
    patch_path: str | None
    status: str
    valid: bool
    metrics: dict[str, float]
    feedback: dict[str, Any]
    error: str | None


class ProgramDB:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def close(self) -> None:
        self.conn.close()

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS runs (
              run_id TEXT PRIMARY KEY,
              task_path TEXT NOT NULL,
              state TEXT NOT NULL,
              best_candidate TEXT,
              stop_reason TEXT,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP,
              updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS candidates (
              candidate_id TEXT PRIMARY KEY,
              patch_path TEXT,
              parent_ids TEXT NOT NULL DEFAULT '[]',
              status TEXT NOT NULL,
              valid INTEGER NOT NULL DEFAULT 0,
              metrics TEXT NOT NULL DEFAULT '{}',
              feedback TEXT NOT NULL DEFAULT '{}',
              error TEXT,
              touched_files TEXT NOT NULL DEFAULT '[]',
              created_at TEXT DEFAULT CURRENT_TIMESTAMP,
              completed_at TEXT
            );
            """
        )
        self.conn.commit()

    def create_run(self, run_id: str, task_path: Path) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO runs(run_id, task_path, state) VALUES (?, ?, ?)",
            (run_id, str(task_path), "running"),
        )
        self.conn.commit()

    def set_run_state(self, run_id: str, state: str, best_candidate: str | None = None, stop_reason: str | None = None) -> None:
        self.conn.execute(
            """
            UPDATE runs
               SET state = ?, best_candidate = ?, stop_reason = ?, updated_at = CURRENT_TIMESTAMP
             WHERE run_id = ?
            """,
            (state, best_candidate, stop_reason, run_id),
        )
        self.conn.commit()

    def insert_candidate(self, candidate_id: str, patch_path: str | None, parent_ids: list[str] | None = None) -> None:
        self.conn.execute(
            """
            INSERT INTO candidates(candidate_id, patch_path, parent_ids, status)
            VALUES (?, ?, ?, ?)
            """,
            (candidate_id, patch_path, json.dumps(parent_ids or []), "queued"),
        )
        self.conn.commit()

    def complete_candidate(
        self,
        *,
        candidate_id: str,
        valid: bool,
        metrics: dict[str, float],
        feedback: dict[str, Any],
        error: str | None,
        touched_files: list[str] | None = None,
    ) -> None:
        self.conn.execute(
            """
            UPDATE candidates
               SET status = ?, valid = ?, metrics = ?, feedback = ?, error = ?,
                   touched_files = ?, completed_at = CURRENT_TIMESTAMP
             WHERE candidate_id = ?
            """,
            (
                "completed" if valid else "failed",
                1 if valid else 0,
                json.dumps(metrics, sort_keys=True),
                json.dumps(feedback, sort_keys=True),
                error,
                json.dumps(touched_files or []),
                candidate_id,
            ),
        )
        self.conn.commit()

    def list_candidates(self) -> list[CandidateRecord]:
        rows = self.conn.execute("SELECT * FROM candidates ORDER BY candidate_id").fetchall()
        return [
            CandidateRecord(
                candidate_id=row["candidate_id"],
                patch_path=row["patch_path"],
                status=row["status"],
                valid=bool(row["valid"]),
                metrics=json.loads(row["metrics"] or "{}"),
                feedback=json.loads(row["feedback"] or "{}"),
                error=row["error"],
            )
            for row in rows
        ]

    def best_candidate(self, task: TaskSpec) -> CandidateRecord | None:
        valid = [item for item in self.list_candidates() if item.valid and _passes_constraints(item, task)]
        if not valid:
            return None
        primary = task.primary_objective
        if primary is None:
            return valid[0]
        reverse = primary.direction == "maximize"
        return sorted(valid, key=lambda item: item.metrics.get(primary.name, float("-inf") if reverse else float("inf")), reverse=reverse)[0]


def _passes_constraints(candidate: CandidateRecord, task: TaskSpec) -> bool:
    if task.required_metric_names - set(candidate.metrics):
        return False
    for objective in task.objectives.values():
        if not objective.hard_constraint:
            continue
        value = candidate.metrics.get(objective.name)
        if value is None:
            return False
        if objective.minimum is not None and value < objective.minimum:
            return False
        if objective.maximum is not None and value > objective.maximum:
            return False
    return True
