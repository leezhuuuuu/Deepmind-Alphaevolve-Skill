from __future__ import annotations

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from aevolve_runtime.evaluator import evaluate_candidate
from aevolve_runtime.generators import GeneratedPatch, write_agent_prompts, write_generated_patches
from aevolve_runtime.generators.openai_compatible import OpenAICompatibleGenerator
from aevolve_runtime.program_db import ProgramDB
from aevolve_runtime.controller import run_experiment
from aevolve_runtime.patch_engine import apply_replacements, parse_patch
from aevolve_runtime.prompt_sampler import build_mutation_prompt, _truncate
from aevolve_runtime.task_spec import Evaluation, Safety, TaskSpecError, load_task


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
            self.assertTrue((run_dir / "report" / "champion.patch").exists())
            with self.assertRaises(FileExistsError):
                run_experiment(root / "task.yaml", patch_paths=[root / "patches" / "better.patch"], run_id="run-test")

    def test_runtime_rejects_patch_outside_target_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_project(root)
            (root / "patches" / "bad.patch").write_text(
                "FILE: evaluator/public.py\n"
                "<<<<<<< SEARCH\n"
                "import argparse, importlib.util, json, pathlib\n"
                "=======\n"
                "import argparse, importlib.util, json, pathlib\n"
                "# bad edit\n"
                ">>>>>>> REPLACE\n",
                encoding="utf-8",
            )
            run_dir = run_experiment(root / "task.yaml", patch_paths=[root / "patches" / "bad.patch"], run_id="bad-patch")
            status = json.loads((run_dir / "status.json").read_text(encoding="utf-8"))
            self.assertEqual(status["best_candidate"], "c-000000-baseline")
            db = ProgramDB(run_dir / "run.db")
            try:
                candidate = [item for item in db.list_candidates() if item.candidate_id == "c-000001"][0]
                self.assertFalse(candidate.valid)
                self.assertIn("outside allowed target files", candidate.error or "")
            finally:
                db.close()

    def test_runtime_rejects_missing_declared_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_project(root, evaluator_body="missing-score")
            run_dir = run_experiment(root / "task.yaml", patch_paths=[], run_id="missing-metric")
            status = json.loads((run_dir / "status.json").read_text(encoding="utf-8"))
            self.assertIsNone(status["best_candidate"])
            db = ProgramDB(run_dir / "run.db")
            try:
                baseline = db.list_candidates()[0]
                self.assertFalse(baseline.valid)
                self.assertIn("missing required metrics: score", baseline.error or "")
            finally:
                db.close()

    def test_task_spec_rejects_boundary_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_project(root)
            task_text = (root / "task.yaml").read_text(encoding="utf-8")
            (root / "task.yaml").write_text(task_text.replace("- src/solver.py", "- ../outside.py"), encoding="utf-8")
            with self.assertRaises(TaskSpecError):
                load_task(root / "task.yaml", root=root)

            self._write_project(root)
            task_text = (root / "task.yaml").read_text(encoding="utf-8")
            (root / "task.yaml").write_text(
                task_text.replace('output_dir: ".alphaevolve/runs"', 'output_dir: "runs"'),
                encoding="utf-8",
            )
            with self.assertRaises(TaskSpecError):
                load_task(root / "task.yaml", root=root)

            self._write_project(root)
            outside = root.parent / "outside-secret.py"
            outside.write_text("SECRET = True\n", encoding="utf-8")
            try:
                (root / "src" / "solver.py").unlink()
                (root / "src" / "solver.py").symlink_to(outside)
                with self.assertRaises(TaskSpecError):
                    load_task(root / "task.yaml", root=root)
            finally:
                if outside.exists():
                    outside.unlink()

            self._write_project(root)
            with self.assertRaises(ValueError):
                run_experiment(root / "task.yaml", run_id="../escape")

    def test_generation_config_prompt_and_patch_writer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_project(root)
            task_text = (root / "task.yaml").read_text(encoding="utf-8")
            (root / "task.yaml").write_text(
                task_text
                + "generation:\n"
                + "  mode: api\n"
                + "  batch_size: 3\n"
                + "  max_prompt_chars: 1000000\n"
                + "  api:\n"
                + "    provider: deepseek\n"
                + "    base_url: \"https://api.deepseek.com\"\n"
                + "    api_key_env: DEEPSEEK_API_KEY\n"
                + "    model: deepseek-v4-flash\n"
                + "    thinking: enabled\n"
                + "    reasoning_effort: max\n",
                encoding="utf-8",
            )
            task = load_task(root / "task.yaml", root=root)
            self.assertEqual(task.generation.mode, "api")
            self.assertEqual(task.generation.batch_size, 3)
            self.assertEqual(task.generation.max_prompt_chars, 1_000_000)
            self.assertEqual(task.generation.api.model, "deepseek-v4-flash")
            self.assertEqual(task.generation.api.max_tokens, 384_000)
            self.assertEqual(task.generation.api.thinking, "enabled")
            self.assertEqual(task.generation.api.reasoning_effort, "max")

            bundle = build_mutation_prompt(task, candidate_index=7)
            self.assertIn("SEARCH/REPLACE", bundle.system)
            self.assertIn("src/solver.py", bundle.user)
            self.assertIn("def solve():", bundle.user)
            self.assertIn("Generate candidate patch #7", bundle.user)
            self.assertEqual(len(bundle.prompt_hash), 16)

            patch_paths = write_generated_patches(
                [GeneratedPatch("<<<<<<< SEARCH\nx\n=======\ny\n>>>>>>> REPLACE", "unit")],
                root / ".alphaevolve" / "generated" / "unit",
            )
            self.assertEqual(len(patch_paths), 1)
            self.assertTrue(patch_paths[0].exists())
            self.assertTrue((root / ".alphaevolve" / "generated" / "unit" / "manifest.json").exists())

            prompt_paths = write_agent_prompts(task, count=2, output_dir=root / ".alphaevolve" / "agent-prompts" / "unit")
            self.assertEqual(len(prompt_paths), 2)
            prompt_text = prompt_paths[0].read_text(encoding="utf-8")
            self.assertIn("Candidate Worker 1", prompt_text)
            self.assertIn("Return only the patch text", prompt_text)
            self.assertIn("src/solver.py", prompt_text)
            self.assertLessEqual(len(_truncate("x" * 100, 1)), 1)
            self.assertEqual(_truncate("x" * 100, 0), "")

    def test_openai_compatible_generator_uses_configured_endpoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_project(root)
            _FakeCompletionHandler.response_content = (
                "FILE: src/solver.py\n"
                "```python\n"
                "def solve():\n"
                "    return 2\n"
                "```\n"
            )
            server = HTTPServer(("127.0.0.1", 0), _FakeCompletionHandler)
            _FakeCompletionHandler.requests = []
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                task_text = (root / "task.yaml").read_text(encoding="utf-8")
                (root / "task.yaml").write_text(
                    task_text
                    + "generation:\n"
                    + "  mode: api\n"
                    + "  api:\n"
                    + f"    base_url: \"http://127.0.0.1:{server.server_port}\"\n"
                    + "    api_key_env: FAKE_DEEPSEEK_KEY\n"
                    + "    model: deepseek-v4-flash\n"
                    + "    thinking: enabled\n"
                    + "    reasoning_effort: max\n",
                    encoding="utf-8",
                )
                os.environ["FAKE_DEEPSEEK_KEY"] = "unit-secret"
                try:
                    task = load_task(root / "task.yaml", root=root)
                    patches = OpenAICompatibleGenerator().generate(task, count=2)
                finally:
                    os.environ.pop("FAKE_DEEPSEEK_KEY", None)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

            self.assertEqual(len(patches), 2)
            self.assertTrue(patches[0].patch_text.startswith("FILE: src/solver.py"))
            self.assertIn("<<<<<<< SEARCH", patches[0].patch_text)
            self.assertIn("return 2", patches[0].patch_text)
            self.assertEqual(len(_FakeCompletionHandler.requests), 2)
            first_request = _FakeCompletionHandler.requests[0]
            self.assertEqual(first_request["authorization"], "Bearer unit-secret")
            self.assertEqual(first_request["body"]["model"], "deepseek-v4-flash")
            self.assertEqual(first_request["body"]["max_tokens"], 384_000)
            self.assertEqual(first_request["body"]["thinking"]["type"], "enabled")
            self.assertEqual(first_request["body"]["reasoning_effort"], "max")
            self.assertIn("src/solver.py", first_request["body"]["messages"][1]["content"])

    def test_openai_compatible_generator_rejects_untrusted_external_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_project(root)
            task_text = (root / "task.yaml").read_text(encoding="utf-8")
            (root / "task.yaml").write_text(
                task_text
                + "generation:\n"
                + "  mode: api\n"
                + "  api:\n"
                + "    provider: deepseek\n"
                + "    base_url: \"https://evil.example.com\"\n"
                + "    api_key_env: GITHUB_TOKEN\n"
                + "    model: deepseek-v4-flash\n",
                encoding="utf-8",
            )
            os.environ["GITHUB_TOKEN"] = "unit-secret"
            try:
                task = load_task(root / "task.yaml", root=root)
                with self.assertRaisesRegex(RuntimeError, "not trusted|not allowed"):
                    OpenAICompatibleGenerator().generate(task, count=1)
            finally:
                os.environ.pop("GITHUB_TOKEN", None)

    def test_openai_compatible_generator_preserves_supported_file_markers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_project(root)
            _FakeCompletionHandler.response_content = (
                "### FILE: src/solver.py\n"
                "<<<<<<< SEARCH\n"
                "def solve():\n"
                "    return 1\n"
                "=======\n"
                "def solve():\n"
                "    return 2\n"
                ">>>>>>> REPLACE\n"
            )
            server = HTTPServer(("127.0.0.1", 0), _FakeCompletionHandler)
            _FakeCompletionHandler.requests = []
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                task_text = (root / "task.yaml").read_text(encoding="utf-8")
                (root / "task.yaml").write_text(
                    task_text
                    + "generation:\n"
                    + "  mode: api\n"
                    + "  api:\n"
                    + f"    base_url: \"http://127.0.0.1:{server.server_port}\"\n"
                    + "    api_key_env: FAKE_DEEPSEEK_KEY\n"
                    + "    model: deepseek-v4-flash\n",
                    encoding="utf-8",
                )
                os.environ["FAKE_DEEPSEEK_KEY"] = "unit-secret"
                try:
                    task = load_task(root / "task.yaml", root=root)
                    patch = OpenAICompatibleGenerator().generate(task, count=1)[0].patch_text
                finally:
                    os.environ.pop("FAKE_DEEPSEEK_KEY", None)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
            self.assertTrue(patch.startswith("### FILE: src/solver.py"))

    def test_openai_compatible_generator_converts_labeled_search_replace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_project(root)
            _FakeCompletionHandler.response_content = (
                "FILE: src/solver.py\n"
                "SEARCH:\n"
                "def solve():\n"
                "    return 1\n"
                "REPLACE:\n"
                "def solve():\n"
                "    return 2\n"
            )
            server = HTTPServer(("127.0.0.1", 0), _FakeCompletionHandler)
            _FakeCompletionHandler.requests = []
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                task_text = (root / "task.yaml").read_text(encoding="utf-8")
                (root / "task.yaml").write_text(
                    task_text
                    + "generation:\n"
                    + "  mode: api\n"
                    + "  api:\n"
                    + f"    base_url: \"http://127.0.0.1:{server.server_port}\"\n"
                    + "    api_key_env: FAKE_DEEPSEEK_KEY\n"
                    + "    model: deepseek-v4-flash\n",
                    encoding="utf-8",
                )
                os.environ["FAKE_DEEPSEEK_KEY"] = "unit-secret"
                try:
                    task = load_task(root / "task.yaml", root=root)
                    patch = OpenAICompatibleGenerator().generate(task, count=1)[0].patch_text
                finally:
                    os.environ.pop("FAKE_DEEPSEEK_KEY", None)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
            replacements = parse_patch(patch)
            self.assertEqual(replacements[0].search, "def solve():\n    return 1\n")
            self.assertEqual(replacements[0].replace, "def solve():\n    return 2\n")

    def test_evaluator_handles_spaces_and_fails_closed_on_nonzero_json_exit(self) -> None:
        with tempfile.TemporaryDirectory(prefix="aevolve space ") as tmp:
            root = Path(tmp)
            candidate = root / "candidate dir"
            candidate.mkdir(parents=True)
            evaluator = candidate / "eval.py"
            evaluator.write_text(
                "import argparse, json, pathlib, sys\n"
                "p = argparse.ArgumentParser(); p.add_argument('--candidate', required=True); a = p.parse_args()\n"
                "assert pathlib.Path(a.candidate).name == 'candidate dir'\n"
                "print(json.dumps({'valid': False, 'metrics': {'score': 0.0}, 'feedback': {'kept': True}}))\n"
                "sys.exit(1)\n",
                encoding="utf-8",
            )
            result = evaluate_candidate(
                command="python eval.py --candidate {candidate_dir}",
                candidate_dir=candidate,
                repo_root=root,
                evaluation=Evaluation(public_command="", repetitions=1),
                safety=Safety(timeout_seconds=5),
            )
            self.assertFalse(result.valid)
            self.assertEqual(result.metrics, {})
            self.assertIn("evaluator exited 1", result.error or "")

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

    def test_cli_rejects_output_outside_alphaevolve_by_default(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "aevolve_runtime.cli",
                    "agent-prompts",
                    "--task",
                    "examples/toy_solver/task.yaml",
                    "--count",
                    "1",
                    "--out",
                    tmp,
                ],
                cwd=repo,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("output directory must stay under", completed.stderr)

    def test_bin_packing_example_selects_known_improvement(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        run_dir = repo / ".alphaevolve" / "runs" / "unit-bin-packing"
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
                    "examples/bin_packing/task.yaml",
                    "--patch-dir",
                    "examples/bin_packing/patches",
                    "--run-id",
                    "unit-bin-packing",
                ],
                cwd=repo,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            status = json.loads((run_dir / "status.json").read_text(encoding="utf-8"))
            self.assertEqual(status["best_candidate"], "c-000001")
            self.assertEqual(status["best_metrics"]["bins_used"], 58.0)
        finally:
            if run_dir.exists():
                shutil.rmtree(run_dir)

    def test_sorting_network17_baseline_validates_best_known_seed(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        run_dir = repo / ".alphaevolve" / "runs" / "unit-sorting17"
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
                    "examples/sorting_network17/task.yaml",
                    "--run-id",
                    "unit-sorting17",
                ],
                cwd=repo,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            status = json.loads((run_dir / "status.json").read_text(encoding="utf-8"))
            self.assertEqual(status["best_candidate"], "c-000000-baseline")
            self.assertEqual(status["best_metrics"]["size"], 71.0)
            self.assertEqual(status["best_metrics"]["depth"], 12.0)
            self.assertEqual(status["best_metrics"]["correctness"], 1.0)
        finally:
            if run_dir.exists():
                shutil.rmtree(run_dir)

    def _write_project(self, root: Path, evaluator_body: str = "default") -> None:
        if root.exists():
            shutil.rmtree(root)
            root.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        (root / "src").mkdir()
        (root / "evaluator").mkdir()
        (root / "patches").mkdir()
        (root / "src" / "solver.py").write_text("def solve():\n    return 1\n", encoding="utf-8")
        if evaluator_body == "missing-score":
            public_py = (
                "import json\n"
                "print(json.dumps({'valid': True, 'metrics': {'correctness': 1.0}, 'feedback': {}}))\n"
            )
        else:
            public_py = (
                "import argparse, importlib.util, json, pathlib\n"
                "p = argparse.ArgumentParser(); p.add_argument('--candidate', required=True); a = p.parse_args()\n"
                "path = pathlib.Path(a.candidate) / 'src' / 'solver.py'\n"
                "spec = importlib.util.spec_from_file_location('solver', path)\n"
                "mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)\n"
                "value = mod.solve()\n"
                "print(json.dumps({'valid': value in {1, 2}, 'metrics': {'correctness': 1.0, 'score': float(value)}, 'feedback': {'value': value}}))\n"
            )
        (root / "evaluator" / "public.py").write_text(public_py, encoding="utf-8")
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


class _FakeCompletionHandler(BaseHTTPRequestHandler):
    requests: list[dict] = []
    response_content = (
        "```text\n"
        "<<<<<<< SEARCH\n"
        "def solve():\n"
        "    return 1\n"
        "=======\n"
        "def solve():\n"
        "    return 2\n"
        ">>>>>>> REPLACE\n"
        "```"
    )

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        self.__class__.requests.append(
            {
                "path": self.path,
                "authorization": self.headers.get("Authorization"),
                "body": body,
            }
        )
        response = {
            "choices": [
                {
                    "message": {"content": self.__class__.response_content}
                }
            ]
        }
        payload = json.dumps(response).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args) -> None:
        return


if __name__ == "__main__":
    unittest.main()
