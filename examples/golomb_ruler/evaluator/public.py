"""Evaluator for order-9 Golomb ruler constructions."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import time


ORDER = 9
INVALID_LENGTH = 10_000


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", required=True)
    args = parser.parse_args()
    started = time.perf_counter()
    try:
        module = _load_candidate(Path(args.candidate))
        marks = module.construct_marks()
        analysis = _analyze_marks(marks)
        valid = analysis["valid"]
        length = analysis["length"] if valid else INVALID_LENGTH
        metrics = {
            "correctness": 1.0 if valid else 0.0,
            "length": float(length),
            "collision_count": float(analysis["collision_count"]),
            "span_score": float(-length),
            "latency_ms": (time.perf_counter() - started) * 1000,
        }
        feedback = {
            "marks": analysis["marks"],
            "normalized_marks": analysis["normalized_marks"],
            "length": analysis["length"],
            "collision_count": analysis["collision_count"],
            "errors": analysis["errors"],
        }
        print(json.dumps({"valid": valid, "metrics": metrics, "feedback": feedback}, sort_keys=True))
        return 0
    except Exception as exc:
        metrics = {
            "correctness": 0.0,
            "length": float(INVALID_LENGTH),
            "collision_count": float(INVALID_LENGTH),
            "span_score": float(-INVALID_LENGTH),
            "latency_ms": (time.perf_counter() - started) * 1000,
        }
        print(json.dumps({"valid": False, "metrics": metrics, "feedback": {"errors": [str(exc)]}}))
        return 0


def _load_candidate(candidate_dir: Path):
    path = candidate_dir / "examples" / "golomb_ruler" / "src" / "ruler.py"
    spec = importlib.util.spec_from_file_location("candidate_ruler", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load candidate: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "construct_marks"):
        raise RuntimeError("candidate module has no construct_marks")
    return module


def _analyze_marks(raw_marks) -> dict:
    errors: list[str] = []
    if not isinstance(raw_marks, (list, tuple)):
        return _invalid([], [], 0, ["construct_marks must return a list or tuple"])
    if len(raw_marks) != ORDER:
        errors.append(f"expected {ORDER} marks, got {len(raw_marks)}")
    marks: list[int] = []
    for value in raw_marks:
        if isinstance(value, bool) or not isinstance(value, int):
            errors.append(f"mark is not an integer: {value!r}")
        else:
            marks.append(value)
    if len(marks) != len(raw_marks):
        return _invalid(marks, marks, 0, errors)
    normalized = [value - min(marks) for value in marks] if marks else []
    if marks != sorted(marks):
        errors.append("marks must be strictly increasing")
    if len(set(marks)) != len(marks):
        errors.append("marks must be unique")
    if marks and marks[0] != 0:
        errors.append("first mark must be 0")
    if any(value < 0 for value in marks):
        errors.append("marks must be non-negative")

    seen: dict[int, tuple[int, int]] = {}
    collisions: list[dict] = []
    for i, left in enumerate(marks):
        for j in range(i + 1, len(marks)):
            distance = marks[j] - left
            if distance <= 0:
                continue
            if distance in seen:
                collisions.append({"distance": distance, "pairs": [seen[distance], (i, j)]})
            else:
                seen[distance] = (i, j)
    if collisions:
        errors.append("pairwise distances must be unique")
    length = marks[-1] - marks[0] if marks else INVALID_LENGTH
    return {
        "valid": not errors,
        "marks": marks,
        "normalized_marks": normalized,
        "length": length,
        "collision_count": len(collisions),
        "errors": errors,
    }


def _invalid(marks: list[int], normalized: list[int], collisions: int, errors: list[str]) -> dict:
    return {
        "valid": False,
        "marks": marks,
        "normalized_marks": normalized,
        "length": INVALID_LENGTH,
        "collision_count": collisions,
        "errors": errors,
    }


if __name__ == "__main__":
    raise SystemExit(main())
