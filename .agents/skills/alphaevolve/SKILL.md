---
name: alphaevolve
description: Configure, validate, launch, monitor, resume, and review bounded AlphaEvolve-like evolutionary code-search experiments. Use when the user explicitly invokes $alphaevolve or explicitly asks for evaluator-driven algorithm evolution, FunSearch-style search, program mutation plus automatic scoring, or AlphaEvolve-like optimization. Do not use for ordinary bug fixes, one-shot refactors, or routine performance tuning unless there is an executable evaluator and an explicit experiment budget.
---

# AlphaEvolve

## Overview

Use this skill as the control plane for evaluator-driven evolutionary code search. Keep `SKILL.md` focused on workflow and safety; delegate repeated checks to bundled scripts and delegate high-frequency search to an external `aevolve_runtime` CLI or MCP service when available.

## Operating Model

Treat the system as three layers:

- `alphaevolve` skill: inspect the repository, create and validate `TaskSpec`, start or monitor runs, review champions, and report risk.
- `aevolve_runtime`: generate patches, schedule evaluations, maintain the program database, checkpoint state, and expose structured status.
- evaluator sandbox: execute generated candidates with resource limits, no secrets, no network unless explicitly approved, and hidden tests visible only to evaluator code.

Do not run generated candidate code directly in the primary repository. Do not manually carry hundreds of candidates in conversation context. Use structured files under `.alphaevolve/` or runtime APIs.

## Hard Gates

Before launching a run, require:

- An executable evaluator that returns structured metrics.
- A baseline result that can be reproduced.
- Explicit candidate, wall-clock, cost, and parallelism budgets.
- A bounded editable surface such as `EVOLVE-BLOCK` regions or listed files/functions.
- A writable experiment directory, usually `.alphaevolve/`.
- A safety boundary for generated code execution.

Stop and ask the user for confirmation before starting any run that may execute untrusted generated code, use network access, spend external API budget, require credentials, modify files outside `.alphaevolve/`, or write the champion patch back into source files.

## Resource Map

Read only the reference needed for the current task:

- `references/task-spec.md`: use when creating or auditing `.alphaevolve/task.yaml`.
- `references/evaluator-contract.md`: use when writing or validating evaluator output.
- `references/safety-policy.md`: use before any generated-code execution.
- `references/experiment-protocol.md`: use when launching, pausing, resuming, or comparing runs.
- `references/report-format.md`: use when preparing final results.

Use bundled helpers:

- `scripts/aevolve_init.py`: create `.alphaevolve/task.yaml` from the template.
- `scripts/aevolve_validate.py`: perform structural checks on a task spec.
- `scripts/aevolve_run.py`: delegate to `python -m aevolve_runtime.cli run` when the runtime exists.
- `scripts/aevolve_status.py`: summarize a structured run status file.
- `scripts/aevolve_review.py`: summarize champion and report artifacts.

Use bundled assets:

- `assets/task.example.yaml`: starter TaskSpec.
- `assets/evaluator.example.py`: minimal evaluator output example.
- `assets/report.template.md`: report skeleton.

## Workflow

1. Inspect the repository and confirm the target is machine-gradeable.
2. Identify editable regions. Prefer explicit `EVOLVE-BLOCK` markers or a small allowlist of files/functions.
3. Read `references/task-spec.md`, then initialize a task:

   ```bash
   python .agents/skills/alphaevolve/scripts/aevolve_init.py
   ```

4. Edit `.alphaevolve/task.yaml` for the target, objectives, evaluator commands, budget, and safety limits.
5. Read `references/evaluator-contract.md` and validate the evaluator. Run the public baseline only after the user has approved generated-code execution boundaries.
6. Validate the task:

   ```bash
   python .agents/skills/alphaevolve/scripts/aevolve_validate.py --task .alphaevolve/task.yaml
   ```

7. Read `references/safety-policy.md` before launching runtime workers.
8. Launch the runtime only when `aevolve_runtime` exists or the user asks you to scaffold it:

   ```bash
   python .agents/skills/alphaevolve/scripts/aevolve_run.py --task .alphaevolve/task.yaml
   ```

9. Monitor structured state, not free-form logs:

   ```bash
   python .agents/skills/alphaevolve/scripts/aevolve_status.py
   ```

10. Review the champion independently. Read `references/report-format.md`, rerun final validation outside the evolutionary selection loop, then summarize metrics, lineage, cost, risk, and the proposed diff.
11. Do not apply the champion patch to the working tree unless the user explicitly asks for that writeback.

## Runtime Contract

Expect a runtime command shaped like:

```bash
python -m aevolve_runtime.cli run --task .alphaevolve/task.yaml
python -m aevolve_runtime.cli status --run-id <run-id>
python -m aevolve_runtime.cli review --run-id <run-id>
```

If the runtime is missing, explain that the skill is installed but the execution plane still needs to be scaffolded. Offer to create `aevolve_runtime/` as a separate implementation task.

## Definition Of Done

Consider an experiment complete only when:

- The baseline and champion were both evaluated under the same declared protocol.
- The champion passes hidden or holdout validation when available.
- The measured improvement clears the configured significance threshold.
- The run directory preserves task spec, prompts or prompt hashes, patches, metrics, lineage, logs, checkpoints, and final report.
- The final answer names unresolved risks, especially evaluator leakage, overfitting, timing noise, resource limits, and sandbox gaps.
