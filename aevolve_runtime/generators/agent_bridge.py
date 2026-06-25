"""Prompt-file bridge for Codex, Claude Code, or manual patch generators."""

from __future__ import annotations

import json
from pathlib import Path

from aevolve_runtime.prompt_sampler import build_mutation_prompt, render_agent_prompt
from aevolve_runtime.task_spec import TaskSpec


def write_agent_prompts(task: TaskSpec, *, count: int, output_dir: Path) -> list[Path]:
    if count <= 0:
        raise ValueError("count must be positive")
    output_dir.mkdir(parents=True, exist_ok=True)
    prompt_paths: list[Path] = []
    manifest = []
    for index in range(1, count + 1):
        bundle = build_mutation_prompt(
            task,
            candidate_index=index,
            prior_feedback=(
                "You are one worker in a batch. Generate a diverse patch and return only the patch text."
            ),
        )
        path = output_dir / f"agent-request-{index:06d}.md"
        path.write_text(_render_worker_request(bundle, index=index), encoding="utf-8")
        prompt_paths.append(path)
        manifest.append(
            {
                "path": str(path),
                "backend": task.generation.agent.backend,
                "prompt_hash": bundle.prompt_hash,
                "candidate_index": index,
            }
        )
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return prompt_paths


def _render_worker_request(bundle, *, index: int) -> str:
    return (
        f"# Candidate Worker {index}\n\n"
        "Read the request below and produce one candidate SEARCH/REPLACE patch.\n"
        "Return only the patch text in your final answer. Do not edit the repository directly.\n"
        "The orchestrator will save and evaluate the patch separately.\n\n"
        f"{render_agent_prompt(bundle)}\n"
    )
