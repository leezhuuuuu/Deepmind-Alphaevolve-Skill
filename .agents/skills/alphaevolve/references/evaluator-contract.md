# Evaluator Contract

The evaluator is the source of truth. It must be deterministic enough to guide search and strict enough to reject invalid or overfit candidates.

## Output Protocol

Each evaluator command must write one JSON object to stdout:

```json
{
  "valid": true,
  "metrics": {
    "correctness": 1.0,
    "latency_ms": 13.72,
    "memory_mb": 104.3
  },
  "feedback": {
    "failed_cases": [],
    "stderr_excerpt": "",
    "notes": []
  }
}
```

Required fields:

- `valid`: boolean. Set `false` for compile failures, incorrect output, timeouts, policy violations, or metric extraction failures.
- `metrics`: object of numeric scalar metrics. Use raw units. Do not stringify numbers.
- `feedback`: object with concise diagnostic data safe to show to the model.

Optional fields:

- `artifacts`: paths under the run directory, never secret paths.
- `seeds`: random seeds used for this evaluation.
- `timing`: evaluator overhead and candidate runtime details.

## Evaluator Design Rules

- Fail closed. Missing metrics or malformed output must mark the candidate invalid.
- Keep hidden tests hidden from candidate code and mutation prompts.
- Use public tests for search guidance, hidden tests for filtering, and final tests for independent confirmation.
- For runtime metrics, include warmup, repetitions, fixed input sets, and outlier handling.
- For randomized tasks, record seeds and use multiple seeds.
- For correctness, prefer exact checks, property tests, and constraint validation over example-only assertions.
- Prevent candidates from modifying evaluator files, reading answer files, or using caches across candidates.

## Anti-Cheating Checks

Look for candidates that:

- Inspect file names, environment variables, or test directories.
- Skip real computation when they detect benchmark inputs.
- Read hidden data, caches, credentials, or sibling candidate outputs.
- Modify evaluator files or run directories.
- Depend on wall-clock luck or background processes.
- Spawn uncontrolled subprocesses.

If any of these are plausible, add a sandbox rule, hidden test, static scan, or manual review step before trusting improvements.
