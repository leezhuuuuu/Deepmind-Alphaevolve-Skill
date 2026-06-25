#!/usr/bin/env python3
"""Minimal evaluator example for AlphaEvolve-like runs.

Real evaluators should execute the candidate in an isolated directory and emit
exactly one JSON object to stdout.
"""

import argparse
import json
import sys
import time


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", required=True)
    args = parser.parse_args()

    start = time.perf_counter()
    # Replace this stub with correctness tests and benchmark logic.
    valid = bool(args.candidate)
    elapsed_ms = (time.perf_counter() - start) * 1000

    result = {
        "valid": valid,
        "metrics": {
            "correctness": 1.0 if valid else 0.0,
            "latency_ms": elapsed_ms,
            "memory_mb": 0.0,
        },
        "feedback": {
            "failed_cases": [],
            "stderr_excerpt": "",
            "notes": [],
        },
    }
    print(json.dumps(result, sort_keys=True))
    return 0 if valid else 1


if __name__ == "__main__":
    sys.exit(main())
