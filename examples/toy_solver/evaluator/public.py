#!/usr/bin/env python3
"""Toy evaluator for the local AlphaEvolve runtime."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", required=True)
    args = parser.parse_args()

    solver_path = Path(args.candidate) / "examples" / "toy_solver" / "src" / "solver.py"
    spec = importlib.util.spec_from_file_location("toy_solver", solver_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {solver_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    value = module.choose_value()
    valid = isinstance(value, int) and 0 <= value <= 3
    result = {
        "valid": valid,
        "metrics": {
            "correctness": 1.0 if valid else 0.0,
            "score": float(value) if valid else 0.0,
        },
        "feedback": {
            "value": value,
            "notes": [] if valid else ["value must be an integer from 0 to 3"],
        },
    }
    print(json.dumps(result, sort_keys=True))
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
