#!/usr/bin/env python3
"""Summarize final report and champion artifacts for a run."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from aevolve_common import latest_run_dir, load_json, read_text, repo_root


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", default=None, help="Run directory. Defaults to latest .alphaevolve/runs/*")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve() if args.run_dir else latest_run_dir(repo_root())
    if run_dir is None:
        print("No run directory found under .alphaevolve/runs", file=sys.stderr)
        return 2

    status_path = run_dir / "status.json"
    report_path = run_dir / "report" / "report.md"
    champion_patch = run_dir / "report" / "champion.patch"

    print(f"Run directory: {run_dir}")
    if status_path.exists():
        status = load_json(status_path)
        print(f"State: {status.get('state', 'unknown')}")
        print(f"Best candidate: {status.get('best_candidate')}")
        metrics = status.get("best_metrics") or {}
        if metrics:
            print("Best metrics:")
            for key, value in sorted(metrics.items()):
                print(f"  {key}: {value}")
    else:
        print("status.json: missing")

    if report_path.exists():
        print("\nReport excerpt:")
        print(read_text(report_path)[:4000])
    else:
        print("\nreport/report.md: missing")

    if champion_patch.exists():
        print(f"\nChampion patch: {champion_patch}")
    else:
        print("\nreport/champion.patch: missing")
    return 0


if __name__ == "__main__":
    sys.exit(main())
