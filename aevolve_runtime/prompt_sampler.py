"""Prompt construction for candidate patch generators."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from pathlib import Path

from .task_spec import TaskSpec


@dataclass(frozen=True)
class PromptBundle:
    system: str
    user: str
    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def prompt_hash(self) -> str:
        payload = f"{self.system}\n---\n{self.user}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()[:16]

    def messages(self) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": self.system},
            {"role": "user", "content": self.user},
        ]


def build_mutation_prompt(
    task: TaskSpec,
    *,
    candidate_index: int = 1,
    prior_feedback: str | None = None,
) -> PromptBundle:
    """Build a bounded prompt asking for one candidate SEARCH/REPLACE patch."""

    system = (
        "You are an evaluator-driven code mutation engine. Return exactly one patch in SEARCH/REPLACE format. "
        "Do not include markdown fences, explanations, prose, JSON, or shell commands. "
        "Only edit files listed as allowed target files."
    )
    objectives = _render_objectives(task)
    target_files = _render_target_files(task)
    evolve_regions = _render_evolve_regions(task)
    feedback = prior_feedback.strip() if prior_feedback else "No prior feedback is available for this candidate."
    user = f"""Generate candidate patch #{candidate_index}.

Allowed target files:
{_bullet_list(task.target.files)}

Objectives:
{objectives}

Evaluator command:
{task.evaluation.public_command}

Safety and output contract:
- Keep all hard constraints valid.
- Prefer small, reviewable changes that can be evaluated automatically.
- The SEARCH block must match the current source exactly.
- The REPLACE block must contain the full replacement text.
- Use FILE: <path> before a block when editing anything other than the first allowed file.
- Return exactly one patch; no markdown code fences.

Evolve regions:
{evolve_regions}

Prior feedback:
{feedback}

Current source:
{target_files}
"""
    user = _truncate(user, task.generation.max_prompt_chars)
    return PromptBundle(
        system=system,
        user=user,
        metadata={
            "candidate_index": str(candidate_index),
            "task": str(task.path),
            "model_adapter": task.runtime.model_adapter,
        },
    )


def render_agent_prompt(bundle: PromptBundle) -> str:
    """Render a standalone prompt that can be pasted into Codex or Claude Code."""

    return (
        "# AlphaEvolve Candidate Generation Request\n\n"
        "## System\n\n"
        f"{bundle.system}\n\n"
        "## User\n\n"
        f"{bundle.user}"
    )


def _render_objectives(task: TaskSpec) -> str:
    lines = []
    for objective in task.objectives.values():
        bounds = []
        if objective.minimum is not None:
            bounds.append(f"minimum={objective.minimum}")
        if objective.maximum is not None:
            bounds.append(f"maximum={objective.maximum}")
        if objective.hard_constraint:
            bounds.append("hard_constraint=true")
        suffix = f" ({', '.join(bounds)})" if bounds else ""
        lines.append(f"- {objective.name}: {objective.direction}{suffix}")
    return "\n".join(lines)


def _render_evolve_regions(task: TaskSpec) -> str:
    if not task.target.evolve_regions:
        return "- No explicit evolve regions. Stay within allowed target files."
    lines = []
    for region in task.target.evolve_regions:
        marker = ""
        if region.marker_start or region.marker_end:
            marker = f" markers={region.marker_start or ''}..{region.marker_end or ''}"
        lines.append(f"- {region.name}: {region.file}{marker}")
    return "\n".join(lines)


def _render_target_files(task: TaskSpec) -> str:
    sections = []
    for file_name in task.target.files:
        path = task.root / file_name
        sections.append(f"### FILE: {file_name}\n{_read_text(path)}")
    return "\n\n".join(sections)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _bullet_list(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def _truncate(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    marker = "\n\n[Prompt truncated to fit max_prompt_chars]\n\n"
    keep = max(0, max_chars - len(marker))
    head = keep // 2
    tail = keep - head
    return f"{value[:head]}{marker}{value[-tail:]}"
