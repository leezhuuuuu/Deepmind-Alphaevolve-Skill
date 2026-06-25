# TaskSpec Reference

Use `.alphaevolve/task.yaml` as the durable contract between Codex, the runtime, and evaluator workers. Keep it explicit enough that a run can be resumed or audited without relying on conversation history.

## Required Sections

- `target`: source files and allowed evolve regions.
- `objectives`: metrics, direction, hard constraints, and optional weights.
- `budget`: candidate count, parallelism, wall-clock limits, token or cost caps.
- `evaluation`: public, hidden, and final validation commands plus repetitions.
- `safety`: network, filesystem, memory, time, process, and secret boundaries.
- `runtime`: model adapter, patch mode, database path, and output directory.

## Minimal Shape

```yaml
target:
  files:
    - src/solver.py
  evolve_regions:
    - name: solve
      file: src/solver.py
      marker_start: "# EVOLVE-BLOCK-START"
      marker_end: "# EVOLVE-BLOCK-END"

objectives:
  correctness:
    direction: maximize
    hard_constraint: true
    minimum: 1.0
  latency_ms:
    direction: minimize
  memory_mb:
    direction: minimize

budget:
  candidates: 200
  parallelism: 8
  max_wall_seconds: 7200
  stop_after_no_improvement: 40

evaluation:
  public_command: "python evaluator/public.py --candidate {candidate_dir}"
  hidden_command: "python evaluator/hidden.py --candidate {candidate_dir}"
  final_command: "python evaluator/final.py --candidate {candidate_dir}"
  repetitions: 7
  metric_schema_version: 1

safety:
  network: false
  source_readonly: true
  candidate_tmpfs: true
  max_memory_mb: 512
  timeout_seconds: 30
  max_output_bytes: 200000

runtime:
  output_dir: ".alphaevolve/runs"
  database: "sqlite"
  patch_mode: "search_replace"
  model_adapter: "openai"
```

## Authoring Rules

- Prefer explicit evolve regions over whole-repo mutation.
- Keep hidden commands out of candidate-readable directories when possible.
- Use `{candidate_dir}` as the placeholder for the sandboxed candidate checkout.
- Separate correctness from performance metrics.
- Represent lower-is-better metrics with `direction: minimize`; do not negate them in evaluator output.
- Declare repetitions and stop criteria before launching the run.
- Add a `significance` section for noisy benchmarks, for example minimum relative improvement and confidence interval policy.

## Validation Checklist

- All target files exist.
- The public evaluator can run on the baseline.
- The evaluator returns JSON matching `references/evaluator-contract.md`.
- The safety section denies network by default.
- Budget values are finite and small enough for the user's stated intent.
- Runtime output paths are under `.alphaevolve/` unless the user explicitly approves another location.
