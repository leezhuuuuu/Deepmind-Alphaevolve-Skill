#!/usr/bin/env python3
"""Summarize structured AlphaEvolve run status."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from aevolve_common import latest_run_dir, load_json, repo_root


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", default=None, help="Run directory. Defaults to latest .alphaevolve/runs/*")
    parser.add_argument("--json", action="store_true", help="Print raw status JSON")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve() if args.run_dir else latest_run_dir(repo_root())
    if run_dir is None:
        print("No run directory found under .alphaevolve/runs", file=sys.stderr)
        return 2

    status_path = run_dir / "status.json"
    if not status_path.exists():
        print(f"No status.json found in {run_dir}", file=sys.stderr)
        return 2

    status = load_json(status_path)
    if args.json:
        print(json.dumps(status, indent=2, sort_keys=True))
        return 0

    print(f"Run: {status.get('run_id', run_dir.name)}")
    print(f"State: {status.get('state', 'unknown')}")
    print(f"Evaluated: {status.get('evaluated', 0)}")
    print(f"Queued: {status.get('queued', 0)}")
    print(f"Best candidate: {status.get('best_candidate')}")
    best_metrics = status.get("best_metrics") or {}
    if best_metrics:
        print("Best metrics:")
        for key, value in sorted(best_metrics.items()):
            print(f"  {key}: {value}")
    if status.get("stop_reason"):
        print(f"Stop reason: {status['stop_reason']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
