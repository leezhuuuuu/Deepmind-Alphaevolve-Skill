"""Evaluator for the online bin-packing benchmark."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import time


CAPACITY = 100
CASES = [
    [39, 70, 15, 16, 37, 48, 50, 53, 68, 51, 61, 20, 58, 34, 31, 20, 68, 12, 29, 22, 56, 47, 57, 40],
    [20, 36, 61, 52, 32, 65, 64, 57, 58, 66, 51, 41, 20, 20, 44, 14, 60, 29, 40, 64, 49, 17, 70, 41, 16, 46],
    [32, 32, 75, 12, 10, 60, 15, 61, 51, 20, 55, 68, 73, 21, 34, 28, 72, 41, 39, 61, 49, 34, 72, 44, 55, 51],
    [54, 65, 31, 75, 38, 64, 43, 33, 47, 57, 64, 18, 24, 65, 31, 69, 65, 23, 65, 70, 62, 40, 15, 24],
    [70, 65, 49, 16, 56, 28, 13, 44, 73, 24, 47, 55, 67, 71, 29, 74, 28, 42],
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", required=True)
    args = parser.parse_args()

    started = time.perf_counter()
    try:
        module = _load_candidate(Path(args.candidate))
        case_results = [_simulate(module.choose_bin, case) for case in CASES]
        failed_cases = [item for item in case_results if not item["valid"]]
        valid = not failed_cases
        total_bins = sum(item["bins"] for item in case_results)
        total_waste = sum(item["waste"] for item in case_results)
        feedback = {
            "case_bins": [item["bins"] for item in case_results],
            "failed_cases": failed_cases[:3],
        }
        metrics = {
            "correctness": 1.0 if valid else 0.0,
            "bins_used": float(total_bins if valid else 10_000),
            "total_waste": float(total_waste if valid else 10_000),
            "latency_ms": (time.perf_counter() - started) * 1000,
        }
        print(json.dumps({"valid": valid, "metrics": metrics, "feedback": feedback}, sort_keys=True))
        return 0
    except Exception as exc:
        metrics = {
            "correctness": 0.0,
            "bins_used": 10_000.0,
            "total_waste": 10_000.0,
            "latency_ms": (time.perf_counter() - started) * 1000,
        }
        print(json.dumps({"valid": False, "metrics": metrics, "feedback": {"error": str(exc)}}))
        return 0


def _load_candidate(candidate_dir: Path):
    path = candidate_dir / "examples" / "bin_packing" / "src" / "heuristic.py"
    spec = importlib.util.spec_from_file_location("candidate_heuristic", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load candidate: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "choose_bin"):
        raise RuntimeError("candidate module has no choose_bin")
    return module


def _simulate(choose_bin, items: list[int]) -> dict:
    remaining: list[int] = []
    for step, item in enumerate(items):
        choice = choose_bin(item, tuple(remaining))
        if not isinstance(choice, int):
            return {"valid": False, "bins": 10_000, "waste": 10_000, "step": step, "reason": "non-int choice"}
        if choice == -1:
            remaining.append(CAPACITY - item)
            continue
        if choice < 0 or choice >= len(remaining):
            return {"valid": False, "bins": 10_000, "waste": 10_000, "step": step, "reason": "choice out of range"}
        if item > remaining[choice]:
            return {"valid": False, "bins": 10_000, "waste": 10_000, "step": step, "reason": "item does not fit"}
        remaining[choice] -= item
    return {"valid": True, "bins": len(remaining), "waste": sum(remaining)}


if __name__ == "__main__":
    raise SystemExit(main())
