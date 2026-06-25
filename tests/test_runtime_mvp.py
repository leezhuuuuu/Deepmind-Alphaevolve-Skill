from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from aevolve_runtime.controller import run_experiment
from aevolve_runtime.patch_engine import apply_replacements, parse_patch
from aevolve_runtime.task_spec import load_task


class PatchEngineTests(unittest.TestCase):
    def test_parse_and_apply_default_file_patch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "solver.py"
            target.write_text("def solve():\n    return 1\n", encoding="utf-8")
            replacements = parse_patch(
                "<<<<<<< SEARCH\n"
                "def solve():\n"
                "    return 1\n"
                "=======\n"
                "def solve():\n"
                "    return 2\n"
                ">>>>>>> REPLACE\n",
                default_file="solver.py",
            )
            touched = apply_replacements(root, replacements)
            self.assertEqual(touched, ["solver.py"])
            self.assertEqual(target.read_text(encoding="utf-8"), "def solve():\n    return 2\n")


class RuntimeMvpTests(unittest.TestCase):
    def test_runtime_selects_best_patch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_project(root)
            task = load_task(root / "task.yaml", root=root)
            self.assertEqual(task.target.files, ["src/solver.py"])

            run_dir = run_experiment(root / "task.yaml", patch_paths=[root / "patches" / "better.patch"], run_id="run-test")
            status = json.loads((run_dir / "status.json").read_text(encoding="utf-8"))
            self.assertEqual(status["state"], "completed")
            self.assertEqual(status["best_candidate"], "c-000001")
            self.assertEqual(status["best_metrics"]["score"], 2.0)
            self.assertTrue((run_dir / "run.db").exists())
            self.assertTrue((run_dir / "report" / "report.md").exists())

    def test_example_task_runs_through_cli(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        run_dir = repo / ".alphaevolve" / "runs" / "unit-example"
        if run_dir.exists():
            shutil.rmtree(run_dir)
        try:
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "aevolve_runtime.cli",
                    "run",
                    "--task",
                    "examples/toy_solver/task.yaml",
                    "--patch-dir",
                    "examples/toy_solver/patches",
                    "--run-id",
                    "unit-example",
                ],
                cwd=repo,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            status = json.loads((run_dir / "status.json").read_text(encoding="utf-8"))
            self.assertEqual(status["best_candidate"], "c-000001")
            self.assertEqual(status["best_metrics"]["score"], 3.0)
        finally:
            if run_dir.exists():
                shutil.rmtree(run_dir)

    def _write_project(self, root: Path) -> None:
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        (root / "src").mkdir()
        (root / "evaluator").mkdir()
        (root / "patches").mkdir()
        (root / "src" / "solver.py").write_text("def solve():\n    return 1\n", encoding="utf-8")
        (root / "evaluator" / "public.py").write_text(
            "import argparse, importlib.util, json, pathlib\n"
            "p = argparse.ArgumentParser(); p.add_argument('--candidate', required=True); a = p.parse_args()\n"
            "path = pathlib.Path(a.candidate) / 'src' / 'solver.py'\n"
            "spec = importlib.util.spec_from_file_location('solver', path)\n"
            "mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)\n"
            "value = mod.solve()\n"
            "print(json.dumps({'valid': value in {1, 2}, 'metrics': {'correctness': 1.0, 'score': float(value)}, 'feedback': {'value': value}}))\n",
            encoding="utf-8",
        )
        (root / "patches" / "better.patch").write_text(
            "<<<<<<< SEARCH\n"
            "def solve():\n"
            "    return 1\n"
            "=======\n"
            "def solve():\n"
            "    return 2\n"
            ">>>>>>> REPLACE\n",
            encoding="utf-8",
        )
        (root / "task.yaml").write_text(
            "target:\n"
            "  files:\n"
            "    - src/solver.py\n"
            "  evolve_regions: []\n"
            "objectives:\n"
            "  correctness:\n"
            "    direction: maximize\n"
            "    hard_constraint: true\n"
            "    minimum: 1.0\n"
            "  score:\n"
            "    direction: maximize\n"
            "budget:\n"
            "  candidates: 4\n"
            "  parallelism: 2\n"
            "  max_wall_seconds: 300\n"
            "evaluation:\n"
            "  public_command: \"python evaluator/public.py --candidate {candidate_dir}\"\n"
            "  repetitions: 1\n"
            "safety:\n"
            "  network: false\n"
            "  max_memory_mb: 512\n"
            "  timeout_seconds: 10\n"
            "  max_output_bytes: 200000\n"
            "runtime:\n"
            "  output_dir: \".alphaevolve/runs\"\n"
            "  database: \"sqlite\"\n"
            "  patch_mode: \"search_replace\"\n"
            "  model_adapter: \"local\"\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
